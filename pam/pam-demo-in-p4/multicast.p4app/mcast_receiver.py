#!/usr/bin/env python
import argparse

import mcast


parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument('--listen_port', type=int, default=1234)
parser.add_argument('--multicast_group', type=str, default="0.0.0.0") #224.1.2.3

args = parser.parse_args()


def run():
    receiver = mcast.receiver(multicast_group=args.multicast_group, listen_port=args.listen_port)
    receiver.loop()

if __name__ == '__main__':
    run()
