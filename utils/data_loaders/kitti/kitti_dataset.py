import os
import sys
import glob
import random
import torch
import numpy as np
import logging
import json

sys.path.append(os.path.join(os.path.dirname(__file__), '../../..'))
from utils.data_loaders.pointcloud_dataset import *
from utils.visualization.o3d_tools import *
from utils.misc_utils import Timer

class KittiDataset(PointCloudDataset):
  r"""
  Generate single pointcloud frame from KITTI odometry dataset. 
  """
  def __init__(self,
               phase,
               random_rotation=False,
               random_occlusion=False,
               random_scale=False,
               config=None):

    self.root = root = config.kitti_dir 
    self.gp_rem = config.gp_rem
    self.pnv_prep = config.pnv_preprocessing
    self.timer = Timer()

    PointCloudDataset.__init__(self, phase, random_rotation, random_occlusion, random_scale, config)

    logging.info("Initializing KittiDataset")
    logging.info(f"Loading the subset {phase} from {root}")
    if self.gp_rem:
      logging.info("Dataloader initialized with Ground Plane removal.")

    sequences = config.kitti_data_split[phase]
    for drive_id in sequences:
      drive_id = int(drive_id)
      inames = self.get_all_scan_ids(drive_id, is_sorted=True)
      for start_time in inames:
        self.files.append((drive_id,start_time))


  def get_all_scan_ids(self, drive_id, is_sorted=False):
    fnames = glob.glob(self.root + '/sequences/%02d/velodyne/*.bin' % drive_id)
    assert len(
        fnames) > 0, f"Make sure that the path {self.root} has drive id: {drive_id}"
    inames = [int(os.path.split(fname)[-1][:-4]) for fname in fnames]
    if is_sorted:
      return sorted(inames)
    return inames

  def get_velodyne_fn(self, drive, t):
    fname = self.root + '/sequences/%02d/velodyne/%06d.bin' % (drive, t)
    return fname

  def get_pointcloud_tensor(self, drive_id, pc_id):
    fname = self.get_velodyne_fn(drive_id, pc_id)
    xyzr = np.fromfile(fname, dtype=np.float32).reshape(-1, 4)

    if self.gp_rem:
      not_ground_mask = np.ones(len(xyzr), np.bool)
      raw_pcd = make_open3d_point_cloud(xyzr[:,:3], color=None)
      _, inliers = raw_pcd.segment_plane(0.2, 3, 250)
      not_ground_mask[inliers] = 0
      xyzr = xyzr[not_ground_mask]

    if self.pnv_prep:
      xyzr = self.pnv_preprocessing(xyzr)
    if self.random_rotation:
      xyzr = self.random_rotate(xyzr)
    if self.random_occlusion:
      xyzr = self.occlude_scan(xyzr)
    if self.random_scale and random.random() < 0.95:
      scale = self.min_scale + \
          (self.max_scale - self.min_scale) * random.random()
      xyzr = scale * xyzr

    # xyzr_tensor = torch.from_numpy(xyzr)
    # return xyzr_tensor.float()
    return xyzr


  def __getitem__(self, idx): 
    drive_id = self.files[idx][0]
    t0= self.files[idx][1]
    
    xyz0_th = self.get_pointcloud_tensor(drive_id, t0)
    meta_info = {'drive': drive_id, 't0': t0}

    return (xyz0_th,
            meta_info)


#####################################################################################
# Load poses
#####################################################################################

def transfrom_cam2velo(Tcam):
    R = np.array([ 7.533745e-03, -9.999714e-01, -6.166020e-04, 1.480249e-02, 7.280733e-04,
        -9.998902e-01, 9.998621e-01, 7.523790e-03, 1.480755e-02
    ]).reshape(3, 3)
    t = np.array([-4.069766e-03, -7.631618e-02, -2.717806e-01]).reshape(3, 1)
    cam2velo = np.vstack((np.hstack([R, t]), [0, 0, 0, 1]))

    return Tcam @ cam2velo

def load_poses_from_txt(file_name):
    """
    Modified function from: https://github.com/Huangying-Zhan/kitti-odom-eval/blob/master/kitti_odometry.py
    """
    f = open(file_name, 'r')
    s = f.readlines()
    f.close()
    transforms = {}
    positions = []
    for cnt, line in enumerate(s):
        P = np.eye(4)
        line_split = [float(i) for i in line.split(" ") if i != ""]
        withIdx = len(line_split) == 13
        for row in range(3):
            for col in range(4):
                P[row, col] = line_split[row*4 + col + withIdx]
        if withIdx:
            frame_idx = line_split[0]
        else:
            frame_idx = cnt
        transforms[frame_idx] = transfrom_cam2velo(P)
        positions.append([P[0, 3], P[2, 3], P[1, 3]])
    return transforms, np.asarray(positions)


#####################################################################################
# Load timestamps
#####################################################################################


def load_timestamps(file_name):
    # file_name = data_dir + '/times.txt'
    file1 = open(file_name, 'r+')
    stimes_list = file1.readlines()
    s_exp_list = np.asarray([float(t[-4:-1]) for t in stimes_list])
    times_list = np.asarray([float(t[:-2]) for t in stimes_list])
    times_listn = [times_list[t] * (10**(s_exp_list[t]))
                   for t in range(len(times_list))]
    file1.close()
    return times_listn