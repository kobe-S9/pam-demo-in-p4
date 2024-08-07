#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function

import struct
import sys
import socket
import threading
import time
import os

from scapy.all import Packet, IntField, ByteField, sniff


class McastPkt(Packet):
    name = "Mcast packet"
    fields_desc = [
        ByteField('mtype', 0), 
        ByteField('prio', 0), 
        IntField('crate', 0), 
        IntField('nrate', 0)]

McastPkt.size = len(McastPkt())


CONFIG = dict(
    MCAST_NONMULTICAST=0,
    MCAST_NORMAL=1,
    MCAST_FIN=2,
    MCAST_PROBE=3,
    MCAST_FS=4,
    MCAST_PROBE_ACK=5,
    MCAST_NORMAL_ACK=6,
    probe_interval=.1,
    payload_size=1000,
    mheader_size=14+20+8+McastPkt.size,
    max_sending_rate=4000000, #2**31,
    MAX_PRIO_VLAUE=255,
    )


def pack_mcastpkt(mtype=0, prio=0, crate=0, nrate=0, payload="", payload_size=None, **parms):
    if not isinstance(payload, bytearray):
        payload = bytearray(payload, encoding='utf8')
    
    if payload_size is not None:
        payload_size = int(payload_size)
        if len(payload) > payload_size:
            payload = payload[:payload_size]
        else:
            payload = payload + bytearray(payload_size - len(payload))
    header = McastPkt(mtype=mtype, prio=prio, crate=crate, nrate=nrate)
    return bytes(header) + payload

def unpack_mcastpkt(data):
    header = McastPkt(data[:McastPkt.size])
    payload = data[McastPkt.size:]
    return dict(mtype=header.mtype, prio=header.prio, crate=header.crate, nrate=header.nrate, payload=payload, payload_size=len(payload))


class receiver(object):
    """
    https://www.tldp.org/HOWTO/Multicast-HOWTO-6.html
    https://pymotw.com/2/socket/multicast.html
    https://myopsblog.wordpress.com/2016/07/11/how-to-enable-multicast-on-linux-network-interface/
    """
    def __init__(self, multicast_group="224.1.2.3", listen_port=1234, **params):
        self.multicast_group = multicast_group
        self.listen_port = listen_port
        self.last_rate = 0

        self.echo_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #self.logfile_name = "{0}-receiver.log".format(socket.gethostname())
        #os.system("echo  >> {0}".format(self.logfile_name))
        
    def log(self, msg="", level=1):
        #sys.stderr.write(msg)
        #os.system("echo {0} >> {1}".format(msg, self.logfile_name))
        msg = "{0:.6f}, {1}".format(time.time(), msg)
        sys.stdout.write(msg)
        

    def pkt_callback(self, pkt):
        peeraddr = (pkt['IP'].src, pkt['UDP'].sport)
        t = unpack_mcastpkt(bytes(pkt['UDP'].payload))
        if 'payload' in t:
            del t['payload']
        self.log("received '%s' from %s\n" % (str(t), peeraddr))
        if t['mtype'] is CONFIG['MCAST_FIN']:
            return

        t['mtype'] = CONFIG['MCAST_NORMAL']
        #del t['payload']
        del t['payload_size']
        feedback = pack_mcastpkt(**t)
        if t['nrate'] < t['crate'] or t['crate'] < t['nrate'] and (0 == t['crate'] or self.last_rate <= t['crate']):
            feedback = pack_mcastpkt(**t)
            self.log("feedback is sent\n")
            self.echo_sock.sendto(feedback, peeraddr)

    def loop(self):
        if self.multicast_group == 0 or self.multicast_group == '0.0.0.0':
            filter = 'udp and port {1}'.format(self.multicast_group, self.listen_port)
        else:
            filter = 'dst {0} and udp and port {1}'.format(self.multicast_group, self.listen_port)
        
        try:
            sniff(filter=filter, prn=self.pkt_callback, store=0)
        except KeyboardInterrupt:
            print('Interrupted')
            sys.exit(0)
        
    def start(self):
        return self.loop()
    
    def stop(self):
        pass


class sender(object):
    def __init__(self, multicast_group="224.1.2.3", listen_port=1234, **params):
        self.multicast_group = multicast_group
        self.listen_port = listen_port

        self.sending_rate = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ttl = struct.pack('b', 1)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        self.keep_sending = True
        self.sock.settimeout(0.1)

        self.deadline = params.get('deadline', None)

        self.pktnum = params.get('pktnum', 10)
        self.flow_size = params.get('flow_size', CONFIG['payload_size'] * self.pktnum)
        self.flow_remaining_size = self.flow_size
        #self.desired_prio = 0
        self.measured_rates = {}
        self.receiver_num = params.get('receiver_num', 2)
        
        self.policy = params.get('policy', 'pam')
        self.fs = True if self.policy == 'fs' else False

        if self.policy == 'fifo':
            self.get_desired_prio = lambda: max(0, CONFIG['MAX_PRIO_VLAUE'] - int(20 * (time.time() - self.start_time)))
        elif self.policy == 'lifo':
            self.get_desired_prio = lambda: int(20 * (time.time() - self.start_time))
        elif self.policy == 'deadline':
            self.get_desired_prio = self.get_left_time
        else:
            self.get_desired_prio = lambda: int(self.flow_remaining_size / CONFIG['payload_size'])

        self.logfile = None
        threading.Thread(target=self.listen).start()
        
        self.flow_id = '{0}_{1}_{2}_{3}'.format(self.sock.getsockname()[0], self.sock.getsockname()[1], self.multicast_group, self.listen_port)
        self.logfile = open(self.flow_id + '.log', 'w')

    def get_left_time(self):
        t = self.deadline + self.start_time - time.time()
        if t < 0:
            pkt = pack_mcastpkt(mtype=CONFIG['MCAST_FIN'])
            self.send(pkt)
            self.log("# missing deadline: {0}\n".format(time.time() - self.start_time))
            time.sleep(1)
            self.keep_sending = 0
        return int(20 * t)

    def get_desired_prio(self):
        #TODO: to be updated
        return int(self.flow_remaining_size / CONFIG['payload_size'])

    def start(self, start_sleep=0):
        #t1 = time.time()
        #threading.Thread(target=self.listen).start()
        #t2 = time.time()
        #time.sleep(start_sleep)
        self.start_time = time.time()
        self.send_data()

    def log(self, msg="", level=1):
        msg = "{0:.6f}, {1}".format(time.time(), msg)
        if self.logfile is not None:
            self.logfile.write(msg)
        sys.stdout.write(msg)
        
    def listen(self):
        while self.keep_sending:
            try:
                payload, peeraddr = self.sock.recvfrom(70000)
                t = unpack_mcastpkt(payload)
                self.log("get:  '%s' from %s  \n" % (str(t), peeraddr))
                # update sending rate
                self.measured_rates[peeraddr] = t['nrate']
                if len(self.measured_rates) >= self.receiver_num:
                    self.sending_rate = min(self.measured_rates.values())

            except socket.timeout:
                continue

    def send(self, msg):
        return self.sock.sendto(msg, (self.multicast_group, self.listen_port))

    def send_probe(self):
        mtype = CONFIG['MCAST_FS'] if self.fs else CONFIG['MCAST_PROBE']
        while self.sending_rate <= 0:
            pkt = pack_mcastpkt(
                mtype=mtype,
                prio=self.get_desired_prio(),
                nrate=CONFIG['max_sending_rate'])
            log_msg = "sent: dict(mtype={0}, prio={1}, crate={2}, nrate={3}, flowid='{4}')\n".format(
                mtype,
                self.get_desired_prio(),
                self.sending_rate,
                CONFIG['max_sending_rate'],
                self.flow_id)
            self.log(log_msg)
            self.send(pkt)
            time.sleep(CONFIG['probe_interval'])
        

    def send_data(self):
        while self.keep_sending:
            if self.sending_rate <= 0:
                self.send_probe()
            t1 = time.time()
            payload_size = min(CONFIG['payload_size'], self.flow_remaining_size)
            mtype = CONFIG['MCAST_FS'] if self.fs else CONFIG['MCAST_NORMAL']
            pkt = pack_mcastpkt(
                mtype=mtype,
                prio=self.get_desired_prio(), 
                crate=self.sending_rate,
                nrate=CONFIG['max_sending_rate'],
                payload_size=payload_size,
            )
            log_msg = "sent: dict(mtype={0}, prio={1}, crate={2}, nrate={3}, payload_size={4}, flowid='{5}')\n".format(
                mtype,
                self.get_desired_prio(),
                self.sending_rate,
                CONFIG['max_sending_rate'],
                payload_size,
                self.flow_id)
            self.log(log_msg)
            n = self.send(pkt)
            self.flow_remaining_size -= n
            t = time.time() - t1
            next_time = (n + CONFIG['mheader_size']) * 8. / self.sending_rate
            if next_time > t:
                time.sleep(next_time - t)

            if self.flow_remaining_size <= 0:
                pkt = pack_mcastpkt(mtype=CONFIG['MCAST_FIN'])
                self.send(pkt)
                self.log("flow completion time (s): {0}\n".format(time.time() - self.start_time))
                time.sleep(1)
                self.keep_sending = 0
                break
        self.log('sender done!\n')
        if self.logfile is not None:
            self.logfile.close()
            self.logfile = None

    


def dec2bin(x, n=4):
    ret = []
    i = 0
    while x > 0 and n > 0:
        if x >= 1:
            ret.append(i)
            x -= 1
            n -= 1
        x = x * 2
        i += 1
    return ret


def check(x):
    lst = dec2bin(x)
    y = 0
    for i in lst:
        y = y + 1. / (2 ** i)
    print(lst)
    return x, (x-y)/x
    

def gen_cmd(i, n=4, M=32):
    ret = dec2bin(1. / i, n=n)
    ret = ret + [M,] * (n - len(ret))
    return "table_add nrate_division calc_nrate {0} => {1} {2} {3} {4} {5}".format(i, 100000, *ret)

def main():
    for i in range(1, 33):
        print(gen_cmd(i))

if __name__ == '__main__':
    main()
    
