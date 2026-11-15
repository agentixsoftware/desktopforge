#!/usr/bin/python3
"""Agent lab tool: one screenshot from a VM's private VNC Unix socket (RFB 3.8, no auth).

Used for headless virgl guests (--gl without --show), where QMP screendump has no
2D surface. The socket lives in the 0700 lab directory, so only the lab account
can connect. Usage: vnc-screenshot.py SOCKET OUTPUT.png
"""
import socket
import struct
import sys

from PIL import Image


def recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError('VNC server closed the connection')
        data += chunk
    return bytes(data)


def screenshot(path, output):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(20)
    sock.connect(path)
    with sock:
        if not recv_exact(sock, 12).startswith(b'RFB '):
            raise ConnectionError('not an RFB server')
        sock.sendall(b'RFB 003.008\n')
        types = recv_exact(sock, recv_exact(sock, 1)[0])
        if 1 not in types:
            raise ConnectionError('server requires authentication; refusing to proceed')
        sock.sendall(b'\x01')
        if struct.unpack('>I', recv_exact(sock, 4))[0] != 0:
            raise ConnectionError('security handshake failed')
        sock.sendall(b'\x01')  # shared session: do not disconnect other viewers
        width, height = struct.unpack('>HH', recv_exact(sock, 4))
        recv_exact(sock, 16)  # server pixel format, replaced below
        recv_exact(sock, struct.unpack('>I', recv_exact(sock, 4))[0])  # desktop name
        # 32 bpp, little endian, true colour: red at bit 16, green at 8, blue at 0.
        pixel_format = struct.pack('>BBBBHHHBBB3x', 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        sock.sendall(b'\x00\x00\x00\x00' + pixel_format)
        sock.sendall(struct.pack('>BBH', 2, 0, 1) + struct.pack('>i', 0))  # encodings: raw only
        sock.sendall(struct.pack('>BBHHHH', 3, 0, 0, 0, width, height))  # full, non-incremental update
        image = Image.new('RGB', (width, height))
        while True:
            message = recv_exact(sock, 1)[0]
            if message != 0:  # skip anything but FramebufferUpdate (bell, cut text are not expected)
                raise ConnectionError(f'unexpected VNC message {message}')
            recv_exact(sock, 1)
            remaining = struct.unpack('>H', recv_exact(sock, 2))[0]
            covered = 0
            for _ in range(remaining):
                x, y, w, h, encoding = struct.unpack('>HHHHi', recv_exact(sock, 12))
                if encoding != 0:
                    raise ConnectionError(f'unexpected encoding {encoding}')
                pixels = recv_exact(sock, w * h * 4)
                image.paste(Image.frombuffer('RGB', (w, h), pixels, 'raw', 'BGRX', 0, 1), (x, y))
                covered += w * h
            if covered:
                break
        image.save(output)
        return width, height


if __name__ == '__main__':
    print(screenshot(sys.argv[1], sys.argv[2]))
