"""Load config.yaml, apply defaults, then environment overrides (VME_*)."""
import copy
import os

import yaml

DEFAULTS = {
    "morpheus": {
        "url": "",
        "username": "",
        "password": "",
        "api_token": "",
        "client_id": "morph-api",
        "allow_http": False,
        "tls_fingerprint": "",
        "ca_bundle": "",
        "insecure": False,
        "verify_tls": True,  # legacy alias: false == insecure: true
        "timeout": 30,
        "page_size": 250,
    },
    "intervals": {           # seconds
        "metrics": 60,       # hosts, VMs, clusters
        "storage": 300,      # datastores
        "health": 300,       # alarms, appliance health
        "inventory": 900,    # clouds, instances, networks, appliance version
        "lifecycle": 86400,  # OS end-of-life data from endoflife.date
    },
    "retention": {           # days
        "raw": 90,
        "hourly": 730,
        "compress_after": 7,
    },
    "classification": {
        # computeServerType codes to always treat as hypervisor hosts / as VMs
        "host_type_codes": [],
        "vm_type_codes": [],
    },
    "lifecycle": {
        "enabled": True,
        "api": "https://endoflife.date",
        "expected_agent_version": "",  # blank = newest agent version seen in the fleet
        "extra_products": [],          # always fetch these endoflife.date products
        "os_rules": [],                # extra OS detection rules, see config.example.yaml
    },
    "exporters": {
        # Write Prometheus file_sd targets for every HVM host the API reports.
        "enabled": True,
        "targets_dir": "/targets",
        "address": "internal",  # internal | external | hostname  (which host field to scrape)
        "node_port": 9100,      # prometheus-node-exporter
        "libvirt_port": 9177,   # prometheus-libvirt-exporter
        "source": "vme",        # value of the "source" label, to tell several VME estates apart
        "manager_address": "",  # where to scrape node_exporter on the manager; blank = host in morpheus.url
    },
    "log_level": "INFO",
}

ENV_MAP = {
    "VME_URL": ("morpheus", "url"),
    "VME_USERNAME": ("morpheus", "username"),
    "VME_PASSWORD": ("morpheus", "password"),
    "VME_API_TOKEN": ("morpheus", "api_token"),
    "VME_VERIFY_TLS": ("morpheus", "verify_tls"),
    "VME_INSECURE": ("morpheus", "insecure"),
    "VME_TLS_FINGERPRINT": ("morpheus", "tls_fingerprint"),
    "VME_CA_BUNDLE": ("morpheus", "ca_bundle"),
    "LOG_LEVEL": ("log_level",),
}


def _merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _coerce(v):
    low = v.strip().lower()
    if low in ("true", "yes", "1"):
        return True
    if low in ("false", "no", "0"):
        return False
    return v


def load(path=None):
    path = path or os.environ.get("VME_CONFIG", "/config/config.yaml")
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(path):
        with open(path) as f:
            _merge(cfg, yaml.safe_load(f) or {})
    for env, keys in ENV_MAP.items():
        if os.environ.get(env):
            node = cfg
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = _coerce(os.environ[env])
    if not cfg["morpheus"]["url"]:
        raise SystemExit(f"config: morpheus.url is not set (looked in {path} and $VME_URL)")
    return cfg
