#include <core.p4>
#include <v1model.p4>

#include "header.p4"
#include "parser.p4"

const bit<32> PORT_NUM = 32w20;
const bit<32> FLOW_NUM = 32w10000;
const bit<8>  MAX_FLOW_PRIO_VALUE  = 8w255;

const bit<8> MCAST_NONMULTICAST = 0;
const bit<8> MCAST_NORMAL = 1; 
const bit<8> MCAST_FIN = 2;
const bit<8> MCAST_PROBE = 3;
const bit<8> MCAST_FS = 4;
const bit<8> MCAST_NORMAL_ACK = 5;
const bit<8> MCAST_PROBE_ACK = 6;
const bit<19> QUEUE_THRESHOLD = 10;



control egress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    register<bit<32>>(PORT_NUM) selected_flow_rate_reg; 
    register<bit<16>>(PORT_NUM) selected_flow_id_reg; 
    register<bit<8>>(PORT_NUM) selected_flow_prio_reg;
    register<bit<32>>(PORT_NUM) active_flow_num_reg;

    register<bit<32>>(PORT_NUM) mcast_traffic_load_reg;
    register<bit<32>>(PORT_NUM) normal_traffic_load_reg;

    register<bit<32>>(PORT_NUM) available_aggr_bw_reg;
    //register<bit<32>>(PORT_NUM) available_fs1_rate_reg;
    //register<bit<32>>(PORT_NUM) available_fs2_rate_reg;

    register<bit<19>>(PORT_NUM) queuelen_reg;

    register<bit<1>>(FLOW_NUM) active_flow_bf_reg; 


    action rewrite_mac(bit<48> smac) {
        hdr.ethernet.srcAddr = smac;
    }
    action _drop() {
        mark_to_drop();
    }

    action calc_nrate(bit<32> maxrate, bit<8>s1, bit<8>s2, bit<8>s3, bit<8>s4){
        bit<32> rate = ((meta.mcast_metadata.n2rate >> s1)
                        + (meta.mcast_metadata.n2rate >> s2)
                        + (meta.mcast_metadata.n2rate >> s3)
                        + (meta.mcast_metadata.n2rate >> s4));
        rate = (rate > maxrate) ? maxrate : rate; 
        hdr.mcast.nrate = (hdr.mcast.nrate > rate) ? rate : hdr.mcast.nrate; 
    }

    table send_frame {
        actions = {
            rewrite_mac;
            _drop;
            NoAction;
        }
        key = {
            standard_metadata.egress_port: exact;
        }
        size = 256;
        default_action = NoAction();
    }


    table nrate_division {
        actions = {
            calc_nrate;
        }
        key = {
            meta.mcast_metadata.division_num: exact;
        }
        size = 32;
        default_action = calc_nrate(0, (bit<8>) 32, (bit<8>) 32, (bit<8>) 32, (bit<8>) 32);
    }

    apply {
        #define port_index  ((bit<32>)standard_metadata.egress_port)
        if (hdr.ipv4.isValid()) {
            send_frame.apply();
            queuelen_reg.write(port_index, standard_metadata.enq_qdepth);
            if (meta.mcast_metadata.ismulticast == 1w1){
                // ###############################################
                bit<16> selected_flow_id = 0;
                selected_flow_id_reg.read(selected_flow_id, port_index);

                bit<8> selected_flow_prio;
                selected_flow_prio_reg.read(selected_flow_prio, port_index);

                bit<32> selected_flow_rate = 0;
                selected_flow_rate_reg.read(selected_flow_rate, port_index);

                bit<32> active_flow_num = 0;
                active_flow_num_reg.read(active_flow_num, port_index);

                bit<32> mcast_load = 0;
                mcast_traffic_load_reg.read(mcast_load, port_index);

                bit<32> available_aggr_bw = 0;
                available_aggr_bw_reg.read(available_aggr_bw, port_index);

                bit<16> flow_hash;
                hash(
                    flow_hash, 
                    HashAlgorithm.crc16, 
                    16w1, 
                    { hdr.ipv4.srcAddr, hdr.ipv4.dstAddr, hdr.udp.srcPort, hdr.udp.dstPort, port_index}, 
                    FLOW_NUM);
                bit<1> active;
                active_flow_bf_reg.read(active, (bit<32>) flow_hash);

                if (1w1 == active && (MCAST_FIN == hdr.mcast.mtype || MCAST_PROBE == hdr.mcast.mtype)){
                    active = 1w0;
                    active_flow_num = active_flow_num - 1;
                    if (flow_hash == selected_flow_id) {
                        selected_flow_id = 0;
                        selected_flow_rate = 0;
                        selected_flow_prio = MAX_FLOW_PRIO_VALUE;
                    }
                }else if (1w0 == active && (MCAST_NORMAL == hdr.mcast.mtype || MCAST_FS == hdr.mcast.mtype)){
                    active = 1w1;
                    active_flow_num = active_flow_num + 1;
                }

                if (MCAST_FS == hdr.mcast.mtype) {
                    meta.mcast_metadata.n2rate = available_aggr_bw;
                    meta.mcast_metadata.division_num = active_flow_num;
                }else if (MCAST_NORMAL == hdr.mcast.mtype || MCAST_PROBE == hdr.mcast.mtype) {
                    if(hdr.mcast.prio < selected_flow_prio || flow_hash == selected_flow_id){
                        meta.mcast_metadata.n2rate = available_aggr_bw;
                        meta.mcast_metadata.division_num = 1;
                        if (MCAST_NORMAL == hdr.mcast.mtype) {
                            selected_flow_id = flow_hash;
                            selected_flow_rate = hdr.mcast.crate;
                            selected_flow_prio = hdr.mcast.prio;
                        }
                    }else{ // FS
                        meta.mcast_metadata.n2rate = (available_aggr_bw > selected_flow_rate)? available_aggr_bw - selected_flow_rate : 0;
                        meta.mcast_metadata.division_num = (MCAST_NORMAL == hdr.mcast.mtype) ? active_flow_num : active_flow_num + 1;
                    }
                }
                active_flow_bf_reg.write((bit<32>) flow_hash, active);
                active_flow_num_reg.write(port_index, active_flow_num);
                
                mcast_load = mcast_load + (bit<32>) hdr.ipv4.totalLen;

                selected_flow_id_reg.write(port_index, selected_flow_id);
                selected_flow_prio_reg.write(port_index, selected_flow_prio);
                selected_flow_rate_reg.write(port_index, selected_flow_rate);
                mcast_traffic_load_reg.write(port_index, mcast_load);
                // #################
                nrate_division.apply();
                // debug
                //hdr.mcast.crate = (bit<32>) selected_flow_prio;
            }else{
                bit<32> normal_load = 0;
                normal_traffic_load_reg.read(normal_load, port_index);
                normal_load = normal_load + (bit<32>) hdr.ipv4.totalLen;
                normal_traffic_load_reg.write(port_index, normal_load);
            }
        }
    }
}

control ingress(inout headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    action _drop() {
        mark_to_drop();
    }
    action set_nhop(bit<32> nhop_ipv4, bit<9> port) {
        meta.ingress_metadata.nhop_ipv4 = nhop_ipv4;
        standard_metadata.egress_spec = port;
        hdr.ipv4.ttl = hdr.ipv4.ttl + 8w255;
    }
    action multicast(bit<16>mcast_grp) {
        standard_metadata.mcast_grp = mcast_grp;
        meta.ingress_metadata.nhop_ipv4 = hdr.ipv4.dstAddr;
        hdr.ipv4.ttl = hdr.ipv4.ttl + 8w255;
        meta.mcast_metadata.ismulticast = 1w1;
    }
    action set_dmac(bit<48> dmac) {
        hdr.ethernet.dstAddr = dmac;
    }
    table ipv4_lpm {
        actions = {
            _drop;
            set_nhop;
            multicast;
            NoAction;
        }
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        size = 1024;
        default_action = NoAction();
    }
    table forward {
        actions = {
            set_dmac;
            _drop;
            NoAction;
        }
        key = {
            meta.ingress_metadata.nhop_ipv4: exact;
        }
        size = 512;
        default_action = NoAction();
    }
    apply {
        if (hdr.ipv4.isValid()) {
          ipv4_lpm.apply();
          forward.apply();
        }
    }
}

V1Switch(ParserImpl(), verifyChecksum(), ingress(), egress(), computeChecksum(), DeparserImpl()) main;
