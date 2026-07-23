#!/usr/bin/env python3
"""Supply GitHub HTTPS credentials without placing tokens in Git arguments."""

from __future__ import annotations

import os
import sys

prompt = " ".join(sys.argv[1:]).lower()
if "username" in prompt:
    print("x-access-token")
else:
    print(os.environ.get("WIKI_TOKEN", ""))
