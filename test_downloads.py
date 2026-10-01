#!/usr/bin/env python3
"""
STEP 7 - Final Verification Test Script
Tests all 5 URLs using the updated bot extraction pipeline in utils.downloader.
"""

import sys
import platform
import io
import asyncio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from utils.downloader import get_media_info, get_last_media_error

TEST_URLS = [
    ("a) YT Short",        "https://youtube.com/shorts/yhIG-dU8iOY?si=zr9QpRsgwazVBdXj"),
    ("b) IG Story",        "https://www.instagram.com/stories/harshdelhise/3997140938384409783?utm_source=ig_story_item_share&stkn=MW8zbzR4MjM3ZWlxMQ=="),
    ("c) IG Image Post",   "https://www.instagram.com/p/Dd4dW6vkuA9/?img_index=3&stkn=MmRteG1jeGpqd2l5"),
    ("d) Pinterest Image", "https://pin.it/4JyxCE4l3"),
    ("e) X/Twitter Image", "https://x.com/jackofficial_01/status/2105131671628472348"),
]

async def main():
    print("=" * 80)
    print("STEP 7: FINAL VERIFICATION TEST TABLE")
    print("=" * 80)
    results = []

    for label, url in TEST_URLS:
        print(f"Testing {label}...")
        info = await get_media_info(url)
        if info:
            if info.get("is_carousel"):
                res_type = f"Carousel ({info.get('carousel_count', 0)} slides)"
            elif info.get("is_photo"):
                res_type = "Photo"
            else:
                res_type = f"Video ({info.get('duration', 'N/A')})"
            title = info.get("title", "")[:35]
            method = "Direct Extractor / gallery-dl / yt-dlp"
            results.append((label, "PASS", res_type, title, method))
        else:
            err = get_last_media_error(url) or "Failed"
            clean_err = err.split("<br>")[0].replace("<b>", "").replace("</b>", "").replace("\n", " ")[:40]
            results.append((label, "FAIL", "N/A", clean_err, "Login Required (Cookies needed)"))

    print("\n" + "=" * 80)
    print(f"{'URL':<22} | {'Status':<6} | {'Type':<20} | {'Details / Error'}")
    print("=" * 80)
    for label, status, mtype, details, method in results:
        print(f"{label:<22} | {status:<6} | {mtype:<20} | {details}")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
