__author__ = '4423'

import asyncore
import struct
from mimetools import Message
from base64 import b64encode
from hashlib import sha1
from StringIO import StringIO
from lib.Log import Log
from lib.WebSocket.Room import Room
from lib.WebSocket.Handler import Handler as RoomManager


class Client(asyncore.dispatcher_with_send):
    """Web Socket Client connection"""

    SALT = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

    _addr = ()
    _server = None
    _room_id = ""

    _ready_state = "connecting"
    _buffer = ""

    def __init__(self, connection, address, server):
        """Setup Client Object

        Parameters
        ----------
        connection : map
        address : string
        server : lib.WebSocket.Server.Server
        """
        # run parent object
        asyncore.dispatcher_with_send.__init__(self, connection)

        # assign vars
        self._addr = address
        self._server = server

    def handle_read(self):
        """Handle incoming data"""
        if self._ready_state == "connecting":
            self._perform_handshake()
        elif self._ready_state == "open":
            message = self._parse_frame()
            Log.add("Decoded Message: %s" % message)
            self.send(message)

    def _perform_handshake(self):
        """Perform The WebSocket Handshake"""
        try:
            Log.add("Got To Handshake")
            data = self.recv(1024).strip()
            Log.add("Data: %s" % data)
            headers = Message(StringIO(data.split('\r\n', 1)[1]))

            Log.add("Parsed Headers:")
            Log.add(headers)

            if headers.get('Upgrade', None) == 'websocket':
                Log.add("Attempting Handshake")

                # create response key
                key = b64encode(sha1(headers['Sec-WebSocket-Key'] + self.SALT).digest())

                # create response headers
                response = (
                    "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    "Sec-WebSocket-Origin: %s\r\n"
                    "Sec-WebSocket-Accept: %s\r\n\r\n" % (headers["Origin"], key)
                )
                if self.send_bytes(response):
                    Log.add("Handshake successful")
                    self._assign_room(data)
                    self._ready_state = "open"

        except Exception as e:
            Log.add(e.args)

    def _assign_room(self, headers):
        """Assign the client to the room they are trying to join

        Parameters
        ----------
        headers : String
        """
        # split room_id from the headers
        room_id = headers.split('\r\n')[0].split(' ')[1].strip()

        Log.add("Room ID: %s" % room_id)

        # assign self to room
        self._room_id = room_id
        Room.add_to_room(room_id, self)

    def _parse_frame(self):
        """Decode an incoming frame

        Returns
        -------
        String"""
        self._buffer = self.recv(1024).strip()

        if len(self._buffer) == 0:
            return
        code_length = ord(self._buffer[1]) & 127
        i = 0
        frame = ''
        if code_length == 126:
            masks = self._buffer[4:8]
            data = self._buffer[8:]
        elif code_length == 127:
            masks = self._buffer[10:14]
            data = self._buffer[14:]
        else:
            masks = self._buffer[2:6]
            data = self._buffer[6:]

        for dat in data:
            frame += chr(ord(dat) ^ ord(masks[i%4]))
            i += 1

        self._buffer = ""
        return frame

    def _create_frame(self, data):
        """Create a message frame to send back to clients

        Parameters
        ----------
        data : String

        Returns
        -------
        String
        """
        token = '\x81'
        data_length = len(data)

        if data_length < 126:
            token += struct.pack("B", data_length)
        elif data_length <= 0xFFFF:
            token += struct.pack("!BH", 126, data_length)
        else:
            token += struct.pack("!BQ", 127, data_length)

        return '%s%s' % (token, data)

    def send(self, data):
        """Send a message to the room at large

        Parameters
        ----------
        data : String
        """
        if self._ready_state == "open":
            RoomManager.send_to_room(self._room_id, self._create_frame(data))

    def send_bytes(self, data):
        """Send raw data back to the client

        Parameters
        ----------
        data : string

        Returns
        -------
        Boolean
        """
        try:
            asyncore.dispatcher_with_send.send(self, data)
            self._buffer = ""
            return True
        except:
            Log.add("Error sending bytes with dispatcher")

        return False

    def handle_close(self):
        """Cleanup a closed connection"""
        Room.remove_from_room(self._room_id, self)
        self.close()