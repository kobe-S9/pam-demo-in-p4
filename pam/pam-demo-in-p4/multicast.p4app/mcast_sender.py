#!/usr/bin/env python

import time
import argparse

import mcast

parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument('--pktnum', type=int, default=1,
                    help='an integer for the accumulator')
parser.add_argument('--listen_port', type=int, default=1234)
parser.add_argument('--multicast_group', type=str, default="224.1.2.3")
parser.add_argument('--policy', type=str, default="pam")
#parser.add_argument('--policy', action="store_true", default=False)
parser.add_argument('--start_sleep', type=float, default=0)
parser.add_argument('--deadline', type=float, default=0)

args = parser.parse_args()

def run():
    #global t1
    t1 = time.time()
    sender = mcast.sender(
        multicast_group=args.multicast_group, 
        listen_port=args.listen_port, 
        pktnum=args.pktnum, 
        policy=args.policy, 
        deadline=args.deadline)
    st = args.start_sleep + t1 - time.time()
    if st < 0:
        st = 0
    time.sleep(st)
    sender.start()

if __name__ == '__main__':
    run()
