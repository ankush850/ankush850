import urllib.request
import re
import time

def fetch_stats():
    url = "https://github-readme-stats.shion.dev/api?username=ankush850"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xml;q=0.9,image/webp,*/*;q=0.8'
    })
    
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read().decode('utf-8')
                break
        except Exception as e:
            print(f"Attempt {i+1} failed: {e}")
            time.sleep(2)
    else:
        print("Failed to fetch stats after 3 attempts")
        return None, None
        
    stars_match = re.search(r'Total Stars Earned: (\d+)', content)
    commits_match = re.search(r'Total Commits.*?:\s*(\d+)', content)
    
    if not stars_match or not commits_match:
        print("Failed to find stats in response")
        return None, None
        
    return stars_match.group(1), f"{int(commits_match.group(1)):,}"

def update_svg(filepath, stars, commits):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Replace Stars
    content = re.sub(
        r"(<tspan class='key'>Stars</tspan><tspan class='cc'> \.\.\.\.\. </tspan><tspan class='value'>)[\d,]+(</tspan>)",
        rf"\g<1>{stars}\g<2>",
        content
    )
    
    # Replace Commits
    content = re.sub(
        r"(<tspan class='key'>Commits</tspan><tspan class='cc'> \.\.\. </tspan><tspan class='value'>)[\d,]+(</tspan>)",
        rf"\g<1>{commits}\g<2>",
        content
    )
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    stars, commits = fetch_stats()
    if stars and commits:
        print(f"Fetched Stars: {stars}, Commits: {commits}")
        update_svg("dark_mode.svg", stars, commits)
        update_svg("light_mode.svg", stars, commits)
        print("Updated SVGs")
