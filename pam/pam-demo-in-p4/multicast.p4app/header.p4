#ifndef __HEADER_P4__
#define __HEADER_P4__ 1

struct ingress_metadata_t {
    bit<32> nhop_ipv4;
}

struct mcast_metadata_t {
    bit<1> ismulticast;
    bit<32> n2rate;
    bit<32> division_num;
}

header ethernet_t {
    bit<48> dstAddr;
    bit<48> srcAddr;
    bit<16> etherType;
}

header ipv4_t {
    bit<4>  version;
    bit<4>  ihl;
    bit<8>  diffserv;
    bit<16> totalLen;
    bit<16> identification;
    bit<3>  flags;
    bit<13> fragOffset;
    bit<8>  ttl;
    bit<8>  protocol;
    bit<16> hdrChecksum;
    bit<32> srcAddr;
    bit<32> dstAddr;
}

header udp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<16> length_;
    bit<16> checksum;
}

header mcast_t {
    bit<8> mtype;
    bit<8> prio;
    bit<32> crate;
    bit<32> nrate;
}

struct metadata {
    @name("ingress_metadata")
    ingress_metadata_t   ingress_metadata;
    @name("mcast_metadata")
    mcast_metadata_t mcast_metadata;
}

struct headers {
    @name("ethernet")
    ethernet_t  ethernet;
    @name("ipv4")
    ipv4_t      ipv4;
    @name("udp")
    udp_t       udp;
    @name("mcast")
    mcast_t     mcast;
}

#endif // __HEADER_H__
