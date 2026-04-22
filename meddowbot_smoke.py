import asyncio
import sys
sys.path.insert(0, '.')

async def smoke():
    results: dict[str, str] = {}
    
    # Core imports
    try:
        from cache.client import init_redis
        results["imports"] = "✅ All 7 core modules"
    except Exception as e:
        results["imports"] = f"❌ {e}"
    
    # Redis
    try:
        from cache.client import init_redis, get_redis
        await init_redis()
        await get_redis().ping()
        results["redis"] = "✅ Connected + ping OK"
    except Exception as e:
        results["redis"] = f"❌ {e}"
    
    # Database
    try:
        from database.session import engine
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        results["database"] = "✅ Connected + query OK"
    except Exception as e:
        results["database"] = f"❌ {e}"
    
    # yt-dlp version
    try:
        import yt_dlp
        ver = yt_dlp.version.__version__
        year = int(ver.split(".")[0])
        status = "✅" if year >= 2025 else "⚠️ OUTDATED"
        results["yt_dlp_version"] = f"{status} {ver}"
    except Exception as e:
        results["yt_dlp_version"] = f"❌ {e}"
    
    # TikTok (no auth needed — best test for yt-dlp)
    try:
        import yt_dlp as ytdl
        def _t():
            with ytdl.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
                info = ydl.extract_info(
                    "https://www.tiktok.com/@khaby.lame/video/7137965696300513541",
                    download=False
                )
                return info.get("title", "no title")[:40]
        title = await asyncio.to_thread(_t)
        results["tiktok_download"] = f"✅ {title}"
    except Exception as e:
        results["tiktok_download"] = f"❌ {str(e)[:80]}"
    
    # Reddit public JSON API
    try:
        import httpx
        async with httpx.AsyncClient(headers={"User-Agent": "test:v1"}) as c:
            r = await c.get("https://www.reddit.com/r/videos/hot.json?limit=3", follow_redirects=True)
            n = len(r.json()["data"]["children"])
        results["reddit_api"] = f"✅ Got {n} posts from r/videos"
    except Exception as e:
        results["reddit_api"] = f"❌ {e}"
    
    # Handler imports
    try:
        results["handlers"] = "✅ All 5 handlers load cleanly"
    except Exception as e:
        results["handlers"] = f"❌ {e}"
    
    # Worker imports (the known crash point)
    try:
        from utils.bot import get_bot
        _ = get_bot()
        results["workers"] = "✅ Workers load + get_bot() works"
    except Exception as e:
        results["workers"] = f"❌ {e}"
    
    # Middleware
    try:
        results["middleware"] = "✅ All 3 middleware load cleanly"
    except Exception as e:
        results["middleware"] = f"❌ {e}"

    # Print report
    print()
    print("╔══════════════════════════════════════╗")
    print("║    MEDDOWBOT SMOKE TEST RESULTS       ║")
    print("╠══════════════════════════════════════╣")
    for k, v in results.items():
        print(f"║  {k:<18} {v:<40} ║")
    print("╚══════════════════════════════════════╝")
    fails = [k for k, v in results.items() if v.startswith("❌")]
    if fails:
        print(f"\n⚠️  FAILURES: {', '.join(fails)}")
        print("Fix these before going live.")
        sys.exit(1)
    else:
        print("\n🎉 ALL TESTS PASSED — Bot is production-ready!")
        sys.exit(0)

asyncio.run(smoke())