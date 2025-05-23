#!/usr/bin/env python3

import setuptools

setuptools.setup(
    name="VESC Config Editor",
    version="0.1.0",
    description="Manager for editing VESC configuration files",
    license="MIT",
    py_modules=[],
    install_requires=[
        "commonwealth == 0.1.0",
        "fastapi == 0.105.0",
        # Enforce anyio fastapi subdependency to avoid conflict with starlette
        "anyio == 3.7.1",
        "fastapi-versioning == 0.9.1",
        "loguru == 0.5.3",
        "uvicorn == 0.13.4",
    ],
)