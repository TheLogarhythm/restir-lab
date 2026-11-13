# Copyright (c) 2014-2021, NVIDIA CORPORATION. All rights reserved.
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""Reproduce Donut's procedural sky on Falcor's lat-long environment grid.

Derived from NVIDIA Donut sky.hlsli and SkyPass.cpp, copyright NVIDIA;
those files' MIT license applies to the corresponding formulas below. Pixel
values approximate RTXDI's RGBA16_FLOAT bake, not bit-identical GPU output.
"""
import math
import numpy as np


def direction_from_uv(u, v):
    phi = np.pi * (2 * np.asarray(u) - 1)
    theta = np.pi * np.asarray(v)
    return np.stack((np.sin(theta)*np.sin(phi), np.cos(theta),
                     -np.sin(theta)*np.cos(phi)), axis=-1)


def _smoothstep(a, b, x):
    t = np.clip((x-a)/(b-a), 0., 1.)
    return t*t*(3.-2.*t)


def evaluate_sky(directions, direction_to_light, *, pixel_angle,
                 sun_irradiance=1., sun_color=(1.,1.,1.), sun_angular_size_degrees=1.,
                 sky_color=(.17,.37,.65), horizon_color=(.50,.70,.92),
                 ground_color=(.62,.59,.55), up=(0.,1.,0.), brightness=.1,
                 horizon_degrees=30., glow_degrees=5., glow_intensity=.1,
                 glow_sharpness=4., max_light_radiance=100.):
    directions = np.asarray(directions, dtype=np.float64)
    light = np.asarray(direction_to_light, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)
    if directions.shape[-1:] != (3,) or light.shape != (3,) or up.shape != (3,):
        raise ValueError('Expected 3D directions')
    norm = np.linalg.norm(directions, axis=-1, keepdims=True)
    if (not np.isfinite(directions).all() or not np.isfinite(light).all()
            or not np.isfinite(up).all() or np.any(norm == 0)
            or np.linalg.norm(light) == 0 or np.linalg.norm(up) == 0
            or not (pixel_angle > 0 and horizon_degrees > 0 and glow_degrees > 0)):
        raise ValueError('Invalid sky direction or angular parameter')
    directions = directions / norm
    light /= np.linalg.norm(light)
    up /= np.linalg.norm(up)
    elevation = np.arcsin(np.clip(directions @ up, -1., 1.))
    top = _smoothstep(0., math.radians(horizon_degrees), elevation)[...,None]
    bottom = _smoothstep(0., math.radians(horizon_degrees), -elevation)[...,None]
    horizon = np.asarray(horizon_color)*brightness
    ground = np.asarray(ground_color)*brightness
    sky = np.asarray(sky_color)*brightness
    environment = (horizon*(1-bottom)+ground*bottom)*(1-top)+sky*top
    angular_size = math.radians(np.clip(sun_angular_size_degrees, .1, 90.))
    radiance = sun_irradiance / (4*math.pi*math.sin(angular_size*.5)**2)
    if max_light_radiance > 0:
        radiance = min(radiance, max_light_radiance)
    angle = np.arccos(np.clip(directions @ light, 0., 1.))
    half = angular_size*.5
    disk = np.clip(1-_smoothstep(half-pixel_angle*2, half+pixel_angle*2, angle),0,1)**4
    glow = glow_intensity*np.clip(2*(1-_smoothstep(half-math.radians(glow_degrees),
                                                    half+math.radians(glow_degrees),angle)),0,1)**glow_sharpness
    return environment + np.maximum(disk,glow)[...,None]*radiance*np.asarray(sun_color)


def generate_image(width, height, direction_to_light, **kwargs):
    if not isinstance(width,int) or not isinstance(height,int) or width <= 0 or height <= 0:
        raise ValueError('Image dimensions must be positive integers')
    u = (np.arange(width, dtype=np.float64)+.5)/width
    v = (np.arange(height, dtype=np.float64)+.5)/height
    uu, vv = np.meshgrid(u,v)
    image = evaluate_sky(direction_from_uv(uu,vv), direction_to_light,
                         pixel_angle=4*math.pi/height, **kwargs)
    if not np.isfinite(image).all() or np.max(np.abs(image)) > np.finfo(np.float16).max:
        raise ValueError('Sky cannot be represented in RGBA16_FLOAT')
    return image.astype(np.float16).astype(np.float32)

