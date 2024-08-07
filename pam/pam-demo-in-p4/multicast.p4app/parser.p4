parser ParserImpl(packet_in packet, out headers hdr, inout metadata meta, inout standard_metadata_t standard_metadata) {
    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            16w0x800: parse_ipv4;
            default: accept;
        }
    }
    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            8w17: parse_udp;
            default: accept;
        }
        //transition accept;
    }
    state parse_udp {
        packet.extract(hdr.udp);
        transition select(hdr.udp.length_) {
            //16w0 .. 16w9:   accept;
            //To update
            16w0 &&& 16w0xFFF8: accept;
            16w8 &&& 16w0xFFFE: accept;
            //16w4:   accept;
            //16w5:   accept;
            default:        parse_mcast;
        }
    }
    state parse_mcast{
        packet.extract(hdr.mcast);
        transition accept;
    }
    state start {
        transition parse_ethernet;
    }
}

control DeparserImpl(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.udp);
        packet.emit(hdr.mcast);
    }
}

control verifyChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

control computeChecksum(inout headers hdr, inout metadata meta) {
    apply {
        update_checksum(
            hdr.ipv4.isValid(),
            { hdr.ipv4.version, hdr.ipv4.ihl, hdr.ipv4.diffserv,
            hdr.ipv4.totalLen, hdr.ipv4.identification,
            hdr.ipv4.flags, hdr.ipv4.fragOffset, hdr.ipv4.ttl,
            hdr.ipv4.protocol, hdr.ipv4.srcAddr, hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16);
        /*
        update_checksum_with_payload(
            hdr.mcast.isValid(), 
            {   hdr.ipv4.srcAddr, 
                hdr.ipv4.dstAddr, 
                8w0, hdr.ipv4.protocol, hdr.udp.length_, 
                hdr.udp.srcPort, hdr.udp.dstPort, 
                hdr.udp.length_, 16w0
            }, 
            hdr.udp.checksum, 
            HashAlgorithm.csum16);
            */
    }
}
