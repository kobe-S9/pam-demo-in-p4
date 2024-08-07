import subprocess

from mininet.topo import Topo


def isInt(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


class AppTopo(Topo):
    def __init__(self, manifest=None, target=None, **opts):
        Topo.__init__(self, **opts)

        self.ip_info = {}

        self.tor = {}

        self.manifest = manifest
        self.target = target
        self.conf = manifest['targets'][target]

        hosts_names = set()
        switches_names = set()
        sorted_links = sorted(self.conf['links'])
        for (u, v) in sorted_links:
            for nn in (u, v):
                if nn.startswith('h') or nn in self.conf['hosts']: 
                    hosts_names.add(nn)
                elif nn.startswith('s') or nn in self.conf['switches']: 
                    switches_names.add(nn)
                else:
                    raise Exception("Unknown node type: " + str(nn))
            if u.startswith('h') and v.startswith('s'):
                self.tor[u] = v
            elif v.startswith('h') and u.startswith('s'):
                self.tor[v] = u
        
        self.switches_ids = {}
        for i, s in enumerate(sorted(switches_names)):
            self.switches_ids[s] = i + 1
            self.ip_info[s] = "10.0.20.{0}".format(i + 1)
            self.addSwitch(s)

        self.hosts_ids = {}
        for i, h in enumerate(sorted(hosts_names)):
            self.hosts_ids[h] = i + 1
            host_ip = "10.0.10.{0}".format(i + 1)
            self.ip_info[h] = host_ip
            tor_ip = self.ip_info[self.tor[h]]
            self.addHost(h) 
            #, ip=host_ip + '/32', defaultRoute='via '+ tor_ip)


        for (node1, node2) in sorted_links:
            self.addLink(node1, node2)


class AppController:
    """
    configure hosts, load commands
    """
    def __init__(self, manifest=None, target=None, net=None, cli_path='simple_switch_CLI', **pp):
        self.manifest = manifest
        self.target = target
        self.cli_path = cli_path
        self.conf = manifest['targets'][target]
        self.net = net
        self.topo = net.topo
        
        self.switches = self.topo.switches()

        self.command_files = {sw: [] for sw in self.switches}
        self.commands = {sw: [] for sw in self.switches}

        self.mcast_groups_files = {sw: [] for sw in self.switches}
        self.mcast_groups = {sw: {} for sw in self.switches}
        self.last_mcnoderid = 0

    def start(self):
        self.configureHosts()
        self.generateCommands()
        self.sendGeneratedCommands()
        self.setupMcastGroups()
        self.configurePaths()

    def readCommands(self, filename):
        commands = []
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                if line == '': 
                    continue
                if line[0] == '#': 
                    continue # ignore comments
                commands.append(line)
        return commands

    def parseCliOutput(self, s):
        parsed = dict(raw=s)
        if 'created with handle' in s:
            parsed['handle'] = int(s.split('created with handle', 1)[-1].split()[0])
        return parsed

    def sendCommands(self, commands, thrift_port=9090, sw=None):
        if sw: 
            thrift_port = sw.thrift_port

        print '\n'.join(commands)
        p = subprocess.Popen([self.cli_path, '--thrift-port', str(thrift_port)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        stdout, nostderr = p.communicate(input='\n'.join(commands))
        print stdout
        raw_results = stdout.split('RuntimeCmd:')[1:len(commands)+1]
        parsed_results = map(self.parseCliOutput, raw_results)
        return parsed_results

    def readMcastGroups(self, filename, sw):
        def portForStr(s):
            if isInt(s): 
                return int(s)
            elif s.startswith('h') or s.startswith('s'): 
                return self.topo.port(sw, s)[0]

            raise ValueError

        groups = {}
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                if len(line) is 0 or line.startswith('#'):
                    continue
                a, b = line.split(':')
                mgid = int(a)
                ports = map(portForStr, b.split())
                groups[mgid] = ports

        return groups

    def createMcastGroup(self, mgid, ports, sw=None):
        self.last_mcnoderid += 1
        commands = ['mc_node_create %d %s' % (self.last_mcnoderid, ' '.join(map(str, ports)))]
        results = self.sendCommands(commands, sw=sw)

        handle = results[-1]['handle']
        commands = ['mc_mgrp_create %d' % mgid]

        if 'model' in self.conf and self.conf['model'].lower() != 'bmv2':
            commands += ['mc_associate_node %d %d 0 0' % (mgid, results[-1]['handle'])]
        else:
            commands += ['mc_node_associate %d %d' % (mgid, results[-1]['handle'])]

        self.sendCommands(commands, sw=sw)

    def readRegister(self, register, idx, thrift_port=9090, sw=None):
        if sw: 
            thrift_port = sw.thrift_port
        p = subprocess.Popen([self.cli_path, '--thrift-port', str(thrift_port)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate(input="register_read %s %d" % (register, idx))
        reg_val = filter(lambda l: ' %s[%d]' % (register, idx) in l, stdout.split('\n'))[0].split('= ', 1)[1]
        return long(reg_val)

    def configureHosts(self):
        for h in self.net.hosts:
            h_name = h.name
            h_ip = self.topo.ip_info[h_name]
            h_mac = h.MAC()
            h.setIP(h_ip, prefixLen=32)
            
            s_name = self.topo.tor[h.name]
            s = self.net.get(s_name)
            h_port, s_port = self.topo.port(h_name, s_name)
            s_mac = s.MAC(intf=s.intfs[s_port])
            s_ip = self.topo.ip_info[s_name]
            iface = h.defaultIntf().name
            h.cmd('ifconfig %s %s hw ether %s' % (iface, h_ip, h_mac))
            h.cmd('arp -i %s -s %s %s' % (iface, s_ip, s_mac))
            h.cmd('ethtool --offload %s rx off tx off' % iface)
            h.cmd('ip route add %s dev %s' % (s_ip, iface))
            h.setDefaultRoute("via %s" % s_ip)

    def configurePaths(self):
        return
        for s in  self.net.hosts:
            for d in self.net.hosts:
                if s == d: 
                    continue
                path = self.shortestpath.get(h.name, h2.name, exclude=lambda n: n in self.topo._host_links)
                if not path: 
                    continue
                h_link = self.topo._host_links[h.name][path[1]]
                h2_link = self.topo._host_links[h2.name][path[-2]]
                h.cmd('ip route add %s via %s' % (h2_link['host_ip'], h_link['sw_ip']))

    def generateCommands(self):
        self.loadCommands()
        self.generateDefaultCommands()

    def sendGeneratedCommands(self):
        for sw_name in self.commands:
            sw = self.net.get(sw_name)
            self.sendCommands(self.commands[sw_name], sw=sw)

    def loadCommands(self):
        for sw in self.switches:
            if 'switches' not in self.conf or sw not in self.conf['switches'] or 'commands' not in self.conf['switches'][sw]:
                continue

            extra_commands = self.conf['switches'][sw]['commands']

            if type(extra_commands) == list: # array of commands and/or command files
                for x in extra_commands:
                    if x.endswith('.txt'):
                        self.command_files[sw].append(x)
                    else:
                        self.commands[sw].append(x)
            else: # path to file that contains commands
                self.command_files[sw].append(extra_commands)

        for sw in self.switches:
            for filename in self.command_files[sw]:
                self.commands[sw] += self.readCommands(filename)

    def setupMcastGroups(self):
        self.loadMcastGroups()

        for sw in self.switches:
            for mgid, ports in self.mcast_groups[sw].iteritems():
                self.createMcastGroup(mgid, ports, sw=self.net.get(sw))

    def loadMcastGroups(self):
        for sw in self.switches:
            if 'switches' not in self.conf or sw not in self.conf['switches'] or 'mcast_groups' not in self.conf['switches'][sw]:
                continue

            mcast_groups_files = self.conf['switches'][sw]['mcast_groups']
            if type(mcast_groups_files) == list:
                pass
            elif type(mcast_groups_files) in (str, unicode):
                mcast_groups_files = [mcast_groups_files]
            else:
                raise Exception("`mcast_groups` should either be a filename or a list of filenames")

            self.mcast_groups_files[sw] += mcast_groups_files

        for sw in self.switches:
            for filename in self.mcast_groups_files[sw]:
                self.mcast_groups[sw].update(self.readMcastGroups(filename, sw))


    def configureSwitchesIP(self):
        for s in self.net.switches:
            ip = self.topo.ip_info[s.name]
            for port, intf in s.intfs.items():
                if port is 0:
                    continue
                intf.setIP(ip, prefixLen=32)

        # for h in self.net.hosts


    def generateDefaultCommands(self):
        self.configureSwitchesIP()

        for sw in self.topo.switches():
            if sw not in self.commands: 
                self.commands[sw] = []
            self.commands[sw] += [
                'table_set_default send_frame _drop',
                'table_set_default forward _drop',
                'table_set_default ipv4_lpm _drop']

        for (u, v) in self.topo.links():
            # assert not (v.startswith('h') and v.startswith('h'))
            u_port, v_port = self.topo.port(u, v)
            u_node, v_node = self.net.get(u, v)

            u_ip = u_node.IP(intf=u_node.intfs[u_port])
            u_mac = u_node.MAC(intf=u_node.intfs[u_port])

            v_ip = v_node.IP(intf=v_node.intfs[v_port])
            v_mac = v_node.MAC(intf=v_node.intfs[v_port])

            if not u.startswith('h'): # it is a switch
                self.commands[u].append('table_add send_frame rewrite_mac %d => %s' % (u_port, u_mac))
                self.commands[u].append('table_add forward set_dmac %s => %s' % (v_ip, v_mac))
                self.commands[u].append('table_add ipv4_lpm set_nhop %s/32 => %s %d' % (v_ip, v_ip, u_port))

            if not v.startswith('h'): # it is a switch
                self.commands[v].append('table_add send_frame rewrite_mac %d => %s' % (v_port, v_mac))
                self.commands[v].append('table_add forward set_dmac %s => %s' % (u_ip, u_mac))
                self.commands[v].append('table_add ipv4_lpm set_nhop %s/32 => %s %d' % (u_ip, u_ip, v_port))


    def stop(self):
        pass
