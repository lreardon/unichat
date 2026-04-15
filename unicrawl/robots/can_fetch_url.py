from urllib.robotparser import RobotFileParser


def can_fetch_url(parser: RobotFileParser | None, url: str, force: bool) -> bool:
    if force:
        return True
    if parser is None:
        return True
    return parser.can_fetch("unicrawl", url)
