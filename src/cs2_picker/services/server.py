from typing import Dict, Tuple

import requests

from cs2_picker.core.constants import CLUSTER_DICT, STEAM_SDR_URL


def fetch_server_data() -> Tuple[str, Dict[str, str], Dict[str, str]]:
    response = requests.get(STEAM_SDR_URL, timeout=30)
    response.raise_for_status()
    data = response.json()

    revision = str(data.get("revision", ""))
    if not revision:
        raise ValueError("Failed to fetch server data — empty revision.")

    clustered: Dict[str, str] = {}
    unclustered: Dict[str, str] = {}

    pops = data.get("pops") or {}
    for pop_id, pop_data in pops.items():
        relays = pop_data.get("relays")
        if not relays:
            continue

        ips = [r["ipv4"] for r in relays if r.get("ipv4")]
        if not ips:
            continue

        ip_str = ",".join(ips)
        desc = pop_data.get("desc", pop_id)
        server_name = f"{desc} ({pop_id})"
        is_clustered = False

        for cluster_name, keywords in CLUSTER_DICT.items():
            for keyword in keywords:
                if keyword in server_name:
                    if cluster_name not in clustered:
                        clustered[cluster_name] = ip_str
                    else:
                        clustered[cluster_name] = clustered[cluster_name] + "," + ip_str
                    is_clustered = True

        if server_name not in unclustered:
            unclustered[server_name] = ip_str
        else:
            unclustered[server_name] = unclustered[server_name] + "," + ip_str

        if not is_clustered:
            if server_name not in clustered:
                clustered[server_name] = ip_str
            else:
                clustered[server_name] = clustered[server_name] + "," + ip_str

    return revision, clustered, unclustered


def get_server_dict(
    clustered_mode: bool,
    clustered: Dict[str, str],
    unclustered: Dict[str, str],
) -> Dict[str, str]:
    return clustered if clustered_mode else unclustered
