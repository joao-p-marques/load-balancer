# coding: utf-8

import socket
import select
import signal
import logging
import argparse

# configure logger output format
logging.basicConfig(level=logging.DEBUG,format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',datefmt='%m-%d %H:%M:%S')
logger = logging.getLogger('Load Balancer')


# used to stop the infinity loop
done = False


# implements a graceful shutdown
def graceful_shutdown(signalNumber, frame):  
    logger.debug('Graceful Shutdown...')
    global done
    done = True


# n to 1 policy
class N2One:
    def __init__(self, servers):
        self.servers = servers  

    def select_server(self):
        return self.servers[0]

    def update(*arg):
        pass


# round robin policy
class RoundRobin:
    def __init__(self, servers):
        self.servers = servers
        self.nextServer = 0

    def select_server(self):
        ret = self.servers[self.nextServer]
        # self.nextServer+=1
        # if self.nextServer == len(self.servers):
        #     self.nextServer = 0
        return ret
        
    def update(self):
        self.nextServer+=1
        if self.nextServer == len(self.servers):
            self.nextServer = 0


# least connections policy
class LeastConnections:
    def __init__(self, servers):
        self.servers = servers
        logger.debug('%s', self.servers)
        self.serverConnections = dict()
        for server in self.servers:
            self.serverConnections[server] = 0
        logger.debug("%s", self.serverConnections)

    def select_server(self):
        logger.debug("%s", self.serverConnections)
        minCon = min(self.serverConnections.items(), key=lambda x: x[1])
        return minCon[0]

    def update(self, server, decrement=0):
        logger.debug("%s", self.serverConnections)
        logger.debug("%s", server)
        if not server in self.servers:
            logger.debug('Server not an upstream.')
            return 
        if not decrement:
            self.serverConnections[server]+=1
        else:
            # if self.serverConnections[('localhost', port)] > 0:
            logger.debug('DECREMENTING %s', self.serverConnections[server])
            self.serverConnections[server]-=1


# least response time
class LeastResponseTime:
    def __init__(self, servers):
        self.servers = servers
        self.serverConnections = dict()
        self.serverResponseTime = dict()
        for server in self.servers:
            self.serverConnections[server] = 0
            self.serverResponseTime[server] = 0
        logger.debug("%s", self.serverConnections)

    def select_server(self):
        logger.debug("%s", self.serverConnections)
        minCon = min(self.serverConnections.items(), key=lambda x: x[1])
        return minCon[0]

    def update(self, server, decrement=0):
        logger.debug("%s", self.serverConnections)
        # server = arg[0]
        tmp = self.serverConnections.get(server) # get current number of connections of server passed
        if not decrement:
            self.serverConnections[server] = tmp+1
        else:
            self.serverConnections[server] = tmp-1


class SocketMapper:
    def __init__(self, policy):
        # self.policy = policy
        self.map = {}
        self.sock_map = {}

    def add(self, client_sock, upstream_server):
        upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream_sock.connect(upstream_server)
        logger.debug("Proxying to %s %s", *upstream_server)
        self.map[client_sock] =  upstream_sock
        self.sock_map[upstream_sock] = upstream_server

    def delete(self, sock):
        try:
            # self.policy.update(upstream_server, 1)
            # self.sock_map.pop(self.get_sock(sock))
            self.map.pop(sock)
            sock.close() 
        except KeyError:
            pass

    def get_sock(self, sock):
        for c, u in self.map.items():
            if u == sock:
                return c
            if c == sock:
                return u
        return None

    def get_server(self, sock):
        # logger.debug(self.sock_map)
        if sock in self.sock_map and sock is not None:
            return self.sock_map[sock]
        return None

    def get_all_socks(self):
        """ Flatten all sockets into a list"""
        return list(sum(self.map.items(), ())) 


def main(addr, servers):
    # register handler for interruption 
    # it stops the infinite loop gracefully
    signal.signal(signal.SIGINT, graceful_shutdown)

    # policy = N2One(servers)
    # policy = RoundRobin(servers)
    policy = LeastConnections(servers)
    mapper = SocketMapper(policy)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.setblocking(False)
        sock.bind(addr)
        sock.listen()
        logger.debug("Listening on %s %s", *addr)
        while not done:
            readable, writable, exceptional = select.select([sock]+mapper.get_all_socks(), [], [], 1)
            if readable is not None:
                for s in readable:
                    if s == sock:
                        client, addr = sock.accept()
                        logger.debug("Accepted connection %s %s", *addr)
                        client.setblocking(False)
                        curServer = policy.select_server()
                        mapper.add(client, curServer)
                        policy.update(curServer)
                    if mapper.get_sock(s):
                        data = s.recv(4096)
                        if len(data) == 0: # No messages in socket, we can close down the socket
                            # import pprint
                            # pprint.pprint(s)
                            # pprint.pprint(mapper.get_sock(s))
                            # logger.debug('Socket Address: %s', s.getsockname())

                            server = mapper.get_server(s)
                            if server in servers:
                                if server is not None:
                                    logger.debug('1: %s', server)
                                    policy.update(server, 1)
                            # else:
                            #     # now decrement on other socket
                            #     o_server = mapper.get_server(mapper.get_sock(s))
                            #     if o_server is not None:
                            #         logger.debug('2: %s', o_server)
                            #         policy.update(o_server, 1)

                            mapper.delete(s)
                        else:
                            mapper.get_sock(s).send(data)
    except Exception as err:
        logger.error(err)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pi HTTP server')
    parser.add_argument('-p', dest='port', type=int, help='load balancer port', default=8080)
    parser.add_argument('-s', dest='servers', nargs='+', type=int, help='list of servers ports')
    args = parser.parse_args()
    
    servers = []
    for p in args.servers:
        servers.append(('localhost', p))
    
    main(('127.0.0.1', args.port), servers)
