from urllib.parse import urlparse


def extract_university_name(root_url: str) -> str:
    host = (urlparse(root_url).hostname or "university").lower()
    if host.startswith("www."):
        host = host[4:]

    if host == "unsw.edu.au":
        return "university-of-new-south-wales"

    return host.replace(".", "-")
