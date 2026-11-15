#!/usr/bin/python3 -I
"""Rendering probe: can a compositor get a hardware-accelerated EGL renderer?

Run as a separate process (callers impose a timeout). For each DRM render node
it creates a GBM device, initializes EGL on it the way compositors such as
Niri do, and reports whether the EGL device is a software device
(EGL_MESA_device_software, which Niri refuses) and the GL_RENDERER string.
Prints one JSON object. Standard library and ctypes only; changes nothing.

Callers must give this process a clean environment so overrides such as
LIBGL_ALWAYS_SOFTWARE cannot change the answer.
"""
import ctypes
from ctypes import CFUNCTYPE, POINTER, byref, c_char_p, c_int, c_uint, c_void_p
import glob
import json
import os
import re
import sys

EGL_EXTENSIONS = 0x3055
EGL_NONE = 0x3038
EGL_PLATFORM_GBM_KHR = 0x31D7
EGL_OPENGL_ES_API = 0x30A0
EGL_CONTEXT_CLIENT_VERSION = 0x3098
EGL_DEVICE_EXT = 0x322C
GL_RENDERER = 0x1F01
SOFTWARE_RENDERER = re.compile(r'llvmpipe|softpipe|swrast|lavapipe|software', re.IGNORECASE)


def classify(device_software, renderer):
    """hardware | software | unknown, from the two independent signals."""
    if device_software is True or (renderer and SOFTWARE_RENDERER.search(renderer)):
        return 'software'
    if device_software is False and renderer:
        return 'hardware'
    return 'unknown'


def summarize(nodes):
    """Overall verdict across render nodes."""
    if not nodes:
        return 'none'
    kinds = {n['renderer_class'] for n in nodes}
    if 'hardware' in kinds:
        return 'hardware'
    if kinds == {'software'}:
        return 'software-only'
    return 'unknown'


def _libraries():
    return (ctypes.CDLL('libgbm.so.1'), ctypes.CDLL('libEGL.so.1'), ctypes.CDLL('libGLESv2.so.2'))


def probe_node(path):  # pragma: no cover - needs a real DRM device and Mesa
    record = {'node': path, 'device_software': None, 'renderer': None, 'renderer_class': 'unknown'}
    gbm, egl, gles = _libraries()
    gbm.gbm_create_device.argtypes, gbm.gbm_create_device.restype = [c_int], c_void_p
    gbm.gbm_device_destroy.argtypes = [c_void_p]
    egl.eglGetProcAddress.argtypes, egl.eglGetProcAddress.restype = [c_char_p], c_void_p
    egl.eglInitialize.argtypes, egl.eglInitialize.restype = [c_void_p, POINTER(c_int), POINTER(c_int)], c_uint
    egl.eglBindAPI.argtypes, egl.eglBindAPI.restype = [c_uint], c_uint
    egl.eglCreateContext.argtypes = [c_void_p, c_void_p, c_void_p, POINTER(c_int)]
    egl.eglCreateContext.restype = c_void_p
    egl.eglMakeCurrent.argtypes, egl.eglMakeCurrent.restype = [c_void_p, c_void_p, c_void_p, c_void_p], c_uint
    egl.eglDestroyContext.argtypes = [c_void_p, c_void_p]
    egl.eglTerminate.argtypes = [c_void_p]
    gles.glGetString.argtypes, gles.glGetString.restype = [c_uint], c_char_p

    def proc(name, restype, *argtypes):
        address = egl.eglGetProcAddress(name)
        return CFUNCTYPE(restype, *argtypes)(address) if address else None

    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    device = display = context = None
    try:
        device = gbm.gbm_create_device(fd)
        if not device:
            record['reason'] = 'GBM could not open this device'
            return record
        get_display = proc(b'eglGetPlatformDisplayEXT', c_void_p, c_uint, c_void_p, c_void_p)
        display = get_display(EGL_PLATFORM_GBM_KHR, device, None) if get_display else None
        major, minor = c_int(), c_int()
        if not display or not egl.eglInitialize(display, byref(major), byref(minor)):
            record['reason'] = 'EGL could not initialize on this device'
            return record
        query_display = proc(b'eglQueryDisplayAttribEXT', c_uint, c_void_p, c_int, POINTER(c_void_p))
        query_device = proc(b'eglQueryDeviceStringEXT', c_char_p, c_void_p, c_int)
        if query_display and query_device:
            egl_device = c_void_p()
            if query_display(display, EGL_DEVICE_EXT, byref(egl_device)) and egl_device:
                extensions = query_device(egl_device, EGL_EXTENSIONS) or b''
                record['device_software'] = b'EGL_MESA_device_software' in extensions.split()
        egl.eglBindAPI(EGL_OPENGL_ES_API)
        attributes = (c_int * 3)(EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE)
        context = egl.eglCreateContext(display, None, None, attributes)  # EGL_KHR_no_config_context
        if context and egl.eglMakeCurrent(display, None, None, context):  # surfaceless
            renderer = gles.glGetString(GL_RENDERER)
            record['renderer'] = renderer.decode('utf-8', 'replace')[:200] if renderer else None
        record['renderer_class'] = classify(record['device_software'], record['renderer'])
        return record
    finally:
        if display:
            egl.eglMakeCurrent(display, None, None, None)
            if context:
                egl.eglDestroyContext(display, context)
            egl.eglTerminate(display)
        if device:
            gbm.gbm_device_destroy(device)
        os.close(fd)


def main():  # pragma: no cover - exercised through callers in the VM
    nodes = []
    for path in sorted(glob.glob('/dev/dri/renderD*'))[:8]:
        try:
            nodes.append(probe_node(path))
        except OSError as exc:
            nodes.append({'node': path, 'device_software': None, 'renderer': None,
                          'renderer_class': 'unknown', 'reason': exc.strerror or str(exc)})
    print(json.dumps({'schema_version': 1, 'status': summarize(nodes), 'nodes': nodes}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
