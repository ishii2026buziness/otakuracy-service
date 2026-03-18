"""VTuber (ホロライブ/にじさんじ) group entry collector for IP whitelist."""

VTUBER_GROUPS = [
    {
        "ip_name": "ホロライブ",
        "official_url": "https://hololive.hololivepro.com/",
    },
    {
        "ip_name": "にじさんじ",
        "official_url": "https://www.nijisanji.jp/",
    },
]


class VTuberClient:
    def collect_all(self) -> list[dict]:
        """
        Return VTuber group entries for the IP whitelist.

        Output: [{"title": group_name, "ip_name": group_name, "official_url": url}, ...]
        """
        return [
            {"title": g["ip_name"], "ip_name": g["ip_name"], "official_url": g["official_url"]}
            for g in VTUBER_GROUPS
        ]
