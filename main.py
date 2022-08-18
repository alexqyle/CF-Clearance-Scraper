import argparse
import re
import sys

import httpx
from playwright._impl._api_types import TimeoutError
from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:99.0) Gecko/20100101 Firefox/99.0"
)


def detect_challenge(html: str) -> bool:
    challenge_html = (
        "<title>Please Wait... | Cloudflare</title>",
        "<title>Just a moment...</title>",
        "Checking your browser before accessing",
    )

    return any(x in html for x in challenge_html)


def parse_proxy(args: argparse.Namespace) -> dict:
    if "@" in args.proxy:
        protocol = args.proxy.split("://")[0]
        server = f'{protocol}://{args.proxy.split("@")[1]}'

        username = args.proxy.split("@")[0].split("://")[1].split(":")[0]
        password = args.proxy.split("@")[0].split("://")[1].split(":")[1]

        proxy = {
            "server": server,
            "username": username,
            "password": password,
        }
    else:
        proxy = {"server": args.proxy}

    return proxy


def browser(args: argparse.Namespace) -> dict:
    with sync_playwright() as p:
        if args.verbose:
            print("[+] Launching headless browser...")

        if args.proxy:
            browser = p.firefox.launch(headless=True, proxy=parse_proxy(args))
        else:
            browser = p.firefox.launch(headless=True)

        ms_timeout = args.timeout * 1000

        try:
            context = browser.new_context(user_agent=USER_AGENT)
            context.set_default_timeout(ms_timeout)
            page = context.new_page()
            page.goto(args.url)
        except Exception as e:
            sys.exit("[!] {}".format(str(e).split("\n")[0]) if args.verbose else None)

        verify_button_text = "Verify\s(I|you)\s(am|are)\s(not\sa\sbot|(a\s)?human)"
        verify_button = page.locator(f"text=/{verify_button_text}/")

        try:
            while detect_challenge(page.content()):
                page.wait_for_load_state("networkidle")

                with page.expect_navigation():
                    if re.search(verify_button_text, page.content()):
                        verify_button.click()
                    else:
                        page.reload()
        except TimeoutError:
            pass

        return page.context.cookies()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetches cf_clearance cookies from websites issuing cloudflare challenges to users"
    )
    parser.add_argument(
        "-v", "--verbose", help="Enable verbose logging", action="store_true"
    )
    parser.add_argument(
        "-u",
        "--url",
        help="URL to fetch cf_clearance cookie from",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-f",
        "--file",
        help="File to write the cf_clearance cookie to",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-t",
        "--timeout",
        help="Request timeout (seconds)",
        type=int,
        default=5,
    )
    parser.add_argument(
        "-p",
        "--proxy",
        help="Proxy server to use for requests (SOCKS5 proxy authentication not supported). Example: socks5://172.66.43.144:1080 or http://username:password@172.66.43.144:1080",
        type=str,
        default=None,
    )
    args = parser.parse_args()

    if not args.url:
        sys.exit(parser.print_help())

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-us",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": USER_AGENT,
    }

    try:
        if args.proxy:
            with httpx.Client(
                http2=True,
                follow_redirects=True,
                timeout=args.timeout,
                proxies=args.proxy,
            ) as client:
                init_request = client.get(args.url, headers=headers)
        else:
            with httpx.Client(
                http2=True, follow_redirects=True, timeout=args.timeout
            ) as client:
                init_request = client.get(args.url, headers=headers)
    except Exception as e:
        sys.exit(f"[!] {e}" if args.verbose else None)

    if "<title>Attention Required! | Cloudflare</title>" in init_request.text:
        sys.exit("[!] Cloudflare returned a CAPTCHA page" if args.verbose else None)

    if detect_challenge(init_request.text):
        if args.verbose:
            print(
                "[+] Cloudflare challenge detected. Attempting to fetch cf_clearance cookie..."
            )
    else:
        sys.exit(
            "[!] Cloudflare challenge not detected. Exiting..."
            if args.verbose
            else None
        )

    cookies = browser(args)
    cookie_value = "".join(
        cookie["value"] for cookie in cookies if cookie["name"] == "cf_clearance"
    )

    if not cookie_value:
        sys.exit(
            "[!] Failed to retrieve cf_clearance cookie." if args.verbose else None
        )

    if args.verbose:
        print(f"[+] Cookie: cf_clearance={cookie_value}")
    elif not args.verbose:
        print(f"cf_clearance={cookie_value}")

    if args.file:
        if args.verbose:
            print(f"[+] Writing cf_clearance cookie value to {args.file}...")

        with open(args.file, "a") as file:
            file.write(f"cf_clearance={cookie_value}\n")


if __name__ == "__main__":
    main()
