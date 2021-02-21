import queue
import enum
import logging

from lxml import etree

from . import models
from .client import TAKClient

class Destination(enum.Enum):
    BROADCAST=1
    GROUP=2

class COTRouter:
    def __init__(self, server):
        self.srv = server
        self.clients = set()

        self.event_q = queue.Queue()
        self.lgr = logging.getLogger(self.__class__.__name__)

    def client_connect(self, client):
        self.clients.add(client)

    def client_disconnect(self, client):
        client.close()
        self.clients.discard(client)

    def client_ident(self, client):
        self.lgr.debug("Sending active clients to %s", client)
        for _client in self.clients:
            if _client is client:
                continue
            if _client.user.uid is None:
                continue

            xml = etree.tostring(_client.user.as_element)
            client.sock.sendall(xml)

    def find_client(self, uid=None, callsign=None):
        for client in self.clients:
            if uid and client.user.uid == uid:
                return client
            if callsign and client.user.callsign == callsign:
                return client

        return None

    def find_user(self, uid=None, callsign=None):
        client = self.find_client(uid=uid, callsign=callsign)
        if client is None:
            return None

        return client.user

    def push_event(self, src, event, dst=None):
        if not isinstance(event, (models.Event, etree._Element)):
            raise ValueError("Must be models.Event or lxml Element")

        if dst is None:
            dst = Destination.BROADCAST

        self.event_q.put((src, dst, event))
        self.handle_queue()

    def broadcast(self, src, msg):
        for client in self.clients:
            if client is src:
                continue

            # TODO: Timeouts? select() on writable sockets? Thread safety?
            client.sock.sendall(msg)

    def group_broadcast(self, src, msg, group=None):
        if group is None:
            if isinstance(src, models.TAKUser):
                group = src.group
            elif isinstance(src, TAKClient):
                group = src.user.group
            else:
                raise ValueError("Unable to determine group to send to")

        if not isinstance(group, models.Teams):
            raise ValueError("group must be models.Teams")

        for client in self.clients:
            if client.user is src:
                continue

            if client.user.group == group:
                client.sock.sendall(msg)

    def handle_queue(self):
        try:
            while True:
                (src, dst, evt) = self.event_q.get(False)

                if isinstance(evt, models.Event):
                    xml = etree.tostring(evt.as_element)
                elif isinstance(evt, etree._Element) and evt.tag == 'event':
                    xml = etree.tostring(evt)
                else:
                    self.lgr.warning("Unhandled event queue: %s, %s, %s", src, dst, evt)
                    continue

                if dst is Destination.BROADCAST:
                    self.broadcast(src, xml)
                elif dst is Destination.GROUP:
                    self.group_broadcast(src, xml)
                elif isinstance(dst, models.Teams):
                    self.group_broadcast(src, xml, dst)
                elif isinstance(dst, TAKClient):
                    dst.sock.sendall(xml)
                elif isinstance(dst, models.TAKUser):
                    client = self.find_client(uid=dst.uid)
                    if client is None:
                        self.lgr.warning("Can't find client for %s to deliver message", dst)
                    else:
                        client.sock.sendall(xml)
                else:
                    self.lgr.warning("Don't know what to do!")
        except queue.Empty:
            return
        except Exception as e:
            self.lgr.critical("Unhandled exception", exc_info=e, stack_info=True)
