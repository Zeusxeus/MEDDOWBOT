from __future__ import annotations
import asyncio
import httpx

# Mock settings
class MockSettings:
    class Reddit:
        user_agent = "MEDDOWBOT/1.0"
        max_posts_per_request = 50
    reddit = Reddit()

settings = MockSettings()

async def _fetch_reddit_posts(subreddit: str, count: int, sort: str) -> list[str]:
    """Fetch video URLs from subreddit using Reddit's public JSON API — no API key needed."""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    params = {"limit": min(count * 3, 100)}  # fetch more to filter non-videos
    headers = {"User-Agent": settings.reddit.user_agent}
    
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, params=params, headers=headers)
        
        if response.status_code == 404:
            raise ValueError(f"Subreddit r/{subreddit} not found or private")
        if response.status_code == 403:
            raise ValueError(f"Subreddit r/{subreddit} is private or quarantined")
        
        response.raise_for_status()
        data = response.json()
    
    posts = data.get("data", {}).get("children", [])
    
    video_urls = []
    for post in posts:
        pd = post.get("data", {})
        
        # Skip stickied/pinned posts
        if pd.get("stickied"):
            continue
        
        url_from_pd = pd.get("url", "")
        
        # Reddit native video
        if pd.get("is_video") and pd.get("media"):
            video_urls.append(f"https://www.reddit.com{pd['permalink']}")
        # External video links yt-dlp supports
        elif any(domain in url_from_pd for domain in [
            "youtube.com", "youtu.be", "v.redd.it",
            "streamable.com", "gfycat.com", "redgifs.com",
            "imgur.com", "i.imgur.com", "giphy.com",
            "twitter.com", "x.com", "instagram.com",
            "tiktok.com", "clips.twitch.tv"
        ]):
            video_urls.append(url_from_pd)
        
        if len(video_urls) >= count:
            break
    
    return video_urls[:count]

async def main():
    try:
        posts = await _fetch_reddit_posts("videos", 5, "hot")
        print(f"Success! Found {len(posts)} posts:")
        for p in posts:
            print(f" - {p}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
