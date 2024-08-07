#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
def migrate(register_name, index, source, target, inital_val=0):
    pass
'''
from __future__ import print_function

import os
import re
import sys
import time
import pprint
import json

"""
from os.path import expanduser
home_path = expanduser("~")
sys.path.append(os.path.join(home_path, "bmv2/tools"))
sys.path.append(os.path.join(home_path, "bmv2/targets/simple_switch"))
"""

import runtime_CLI
from sswitch_runtime import SimpleSwitch
from sswitch_CLI import SimpleSwitchAPI



class SSHandler(object):
    def __init__(self, thrift_ip='localhost', thrift_port=9090):
        pre = runtime_CLI.PreType.SimplePreLAG
        services = runtime_CLI.RuntimeAPI.get_thrift_services(pre)
        services.extend(SimpleSwitchAPI.get_thrift_services())

        standard_client, mc_client, sswitch_client = runtime_CLI.thrift_connect(
            thrift_ip, thrift_port, services)

        runtime_CLI.load_json_config(standard_client)

        json_str = standard_client.bm_get_config()
        self.json_dict =  json.loads(json_str)
        
        self.ssapi = SimpleSwitchAPI(pre, standard_client, mc_client, sswitch_client)

    def get_register_info(self, reg_name=None):
        """ 
        "register_arrays": [
        {
            "id": 0,
            "bitwidth": 16,
            "name": "heavy_hitter_counter1",
            "size": 16
        },
        {
            "id": 1,
            "bitwidth": 16,
            "name": "heavy_hitter_counter2",
            "size": 16
        }]
        """
        if not hasattr(self, "__register_info"):
            self.__register_info = {
                it["name"]: it for it in self.json_dict["register_arrays"]
            }
        if reg_name is None:
            return self.__register_info.keys()
        else:
            return self.__register_info[reg_name]

    def show_tables(self):
        self.ssapi.do_show_tables('')

    def get_register_names(self):
        #self.ssapi.
        pass
    
    def table_dump(self, line):
        "Display some (non-formatted) information about a table: table_dump <table_name>"
        self.ssapi.do_table_dump(line)
    
    def get_lpm_entry_handle(self, table_name, key_, prefix_len=32):
        "Get the entry handler of a given match_key in a table"
        #self.ssapi.do_table_dump(table_name)
        def hexstr(v):
            return '0x' + "".join("{:02x}".format(ord(c)) for c in v)
        
        prefix_ip = 0
        for s in key_.split('.'):
            prefix_ip = (prefix_ip << 8) + eval(s)
        
        entries = self.ssapi.client.bm_mt_get_entries(0, table_name)
        for e in entries:
            entry_handle = e.entry_handle
            for item in e.match_key:
                lpm = item.lpm
                if lpm is None:
                    continue
            if lpm.prefix_length == prefix_len and eval(hexstr(lpm.key)) == prefix_ip:
                return entry_handle
        return None

    def register_read(self, register_name, index=None):
        if index is None:
            return  self.ssapi.client.bm_register_read_all(0, register_name)
        else:
            return self.ssapi.client.bm_register_read(0, register_name, index)

    def register_write(self, register_name, index, value):
        return self.ssapi.client.bm_register_write(0, register_name, index, value)
    
    def register_reset(self, register_name):
        self.ssapi.client.bm_register_reset(0, register_name)
    
    def register_fill(self, register_name, start_index=0, end_index=None, value=0):
        if end_index is None:
            end_index = self.get_register_info(register_name)['size']
        self.ssapi.client.bm_register_write_range(0, register_name, start_index, end_index, value)

    
    def get_register_values(self, register_name):
        regsize = self.get_register_info(register_name)['size']
        values = [self.register_read(register_name, i) for i in range(regsize)]
        return values


    def table_modify(self, line):
        "Add entry to a match table: table_modify <table name> <action name> <entry handle> [action parameters]"
        return self.ssapi.do_table_modify(line)

    def table_set_default(self, line):
        "Set default action for a match table: table_set_default <table name> <action name> <action parameters>"
        return self.ssapi.do_table_set_default(line)


def migrate_register_with_controller(source, target, register_name, default_values):
    new_values = source.get_register_values(register_name)

    num_dif_cells = 0
    num_mov_cells = 0
    for index, new_value in enumerate(new_values):
        old_value = target.register_read(register_name, index)
        if old_value != new_value:
            num_dif_cells += 1
            if old_value == default_values[index]:
                num_mov_cells += 1
                target.register_write(register_name, index, new_value)

    print('='*20, register_name, '='*20)
    print(num_mov_cells, 'states are migrated by controller')
    print(num_dif_cells - num_mov_cells, 'states are migrated within data plane')
    print('--'*40)
    return num_dif_cells, num_mov_cells


def dot_netip_to_tuple(s):
    lst = s.split('/')
    if len(lst) != 2:
        return None
    masklen = eval(lst[1])
    addrcells = lst[0].split('.')
    if len(addrcells) != 4:
        return None

    ipaddr = 0
    for cell in addrcells:
        ipaddr = (ipaddr << 8) + eval(cell)

    ipaddr = ipaddr >> (32 - masklen)
    return ipaddr, masklen


def hex_netip_to_tuple(s):
    lst = s.split('/')
    masklen = eval(lst[1])
    ipaddr = eval('0x' + lst[0].strip())
    ipaddr = ipaddr >> (32 - masklen)
    return ipaddr, masklen


def send_cmd_with_os(cmd_str, thrift_port):
    cli = "simple_switch_CLI"
    cmd = 'echo "{0}" | {1} --thrift-port {2}'.format(cmd_str, cli, thrift_port)
    os.system(cmd)


def move_states(port_a, port_b, cared_registers):
    s1 = SSHandler(thrift_port=port_a)
    #s1.show_tables()
    s2 = SSHandler(thrift_port=port_b)
    for reg_name in cared_registers:
        old_values = s2.get_register_values(reg_name)
        migrate_register_with_controller(s1, s2, reg_name, old_values)

    
def main():
    #cared_registers = ["hh_pktcnt"]
    #move_states(9093, 9094, cared_registers)
    #time.sleep(0.1)
    #migrate_s4_to_s3()
    s1 = SSHandler(thrift_port=9090)
    #s1.show_tables()
    reg_names = s1.get_register_info()
    pprint.pprint(reg_names)
    #s1.register_fill("egress.available_aggr_bw_reg", value=200000)
    #s1.register_fill("egress.available_fs1_rate_reg", value=100)
    #s1.register_fill("egress.available_fs2_rate_reg", value=100)
    #s1.register_fill("egress.selected_flow_prio_reg", value=0xff)

    while True:
        print('#' * 30)
        for rn in (
            "egress.selected_flow_rate_reg", 
            "egress.selected_flow_id_reg",  
            "egress.selected_flow_prio_reg", 
            "egress.active_flow_num_reg"):
            t = s1.register_read(rn)
            print(rn)
            print(t)
        time.sleep(1) 



if __name__ == '__main__':
    main()
