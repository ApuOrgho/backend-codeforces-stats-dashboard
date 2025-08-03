from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from collections import Counter, defaultdict
import time
import logging
import datetime
import os

app = Flask(__name__)
CORS(app)

CF_API_BASE = "https://codeforces.com/api"

# Setup simple logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Simple in-memory cache with expiry (60 seconds)
cache = {}

def cached_fetch(url, expiry=60):
    now = time.time()
    if url in cache:
        data, timestamp = cache[url]
        if now - timestamp < expiry:
            logging.info(f"Cache hit for URL: {url}")
            return data, None
        else:
            logging.info(f"Cache expired for URL: {url}")
    # Fetch fresh
    logging.info(f"Fetching URL: {url}")
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data['status'] != 'OK':
            return None, data.get('comment', 'API error')
        cache[url] = (data['result'], now)
        return data['result'], None
    except Exception as e:
        logging.error(f"Error fetching URL {url}: {e}")
        return None, str(e)

def fetch_json(url):
    return cached_fetch(url)

def fetch_user_info(handle):
    url = f"{CF_API_BASE}/user.info?handles={handle}"
    return fetch_json(url)

def fetch_user_submissions(handle):
    url = f"{CF_API_BASE}/user.status?handle={handle}&from=1&count=100000"
    return fetch_json(url)

def fetch_user_rating(handle):
    url = f"{CF_API_BASE}/user.rating?handle={handle}"
    return fetch_json(url)

def fetch_rated_users():
    url = f"{CF_API_BASE}/user.ratedList?activeOnly=true"
    return fetch_json(url)

def calculate_stats(submissions):
    total_submissions = len(submissions)
    accepted_count = 0
    wrong_answer_count = 0
    verdict_counter = Counter()
    attempted_problems = set()
    solved_problems = set()
    first_attempt_solved = set()
    problem_first_submission = {}
    contests_participated = set()

    difficulty_solved = Counter()
    topic_solved = Counter()

    for sub in submissions:
        problem = sub['problem']
        contest_id = problem.get('contestId')
        problem_index = problem.get('index')
        problem_id = (contest_id, problem_index)
        attempted_problems.add(problem_id)
        contests_participated.add(contest_id)

        verdict = sub.get('verdict', 'UNKNOWN')
        verdict_counter[verdict] += 1

        if verdict == "OK":
            accepted_count += 1
            solved_problems.add(problem_id)
            if problem_id not in problem_first_submission:
                problem_first_submission[problem_id] = verdict
                first_attempt_solved.add(problem_id)
            rating = problem.get('rating')
            tags = problem.get('tags', [])
            if rating:
                difficulty_solved[rating] += 1
            for tag in tags:
                topic_solved[tag] += 1
        else:
            if verdict == "WRONG_ANSWER":
                wrong_answer_count += 1
            if problem_id not in problem_first_submission:
                problem_first_submission[problem_id] = verdict

    unique_attempted = len(attempted_problems)
    unique_solved = len(solved_problems)
    problem_solving_rate = round((unique_solved / unique_attempted) * 100, 2) if unique_attempted else 0.0

    problem_attempts = defaultdict(int)
    for sub in submissions:
        pid = (sub['problem'].get('contestId'), sub['problem'].get('index'))
        problem_attempts[pid] += 1
    max_attempts = max(problem_attempts.values()) if problem_attempts else 0
    most_attempted_problems = [pid for pid, c in problem_attempts.items() if c == max_attempts]

    def format_problem(pid):
        return f"{pid[0]}-{pid[1]}"

    return {
        "total_submissions": total_submissions,
        "accepted_count": accepted_count,
        "wrong_answer_count": wrong_answer_count,
        "unique_attempted": unique_attempted,
        "unique_solved": unique_solved,
        "problem_solving_rate": problem_solving_rate,
        "contests_participated": len(contests_participated),
        "first_attempt_solved": len(first_attempt_solved),
        "verdict_counter": dict(verdict_counter),
        "most_attempted_problems": [format_problem(p) for p in most_attempted_problems],
        "max_attempts": max_attempts,
        "difficulty_solved": dict(difficulty_solved),
        "topic_solved": dict(topic_solved),
    }

def analyze_contests(rating_changes):
    total_contests = len(rating_changes)
    contests_skipped = "Not Available"  # Placeholder, needs contest calendar for precise calculation

    best_rank_by_division = {}
    highest_rating = 0
    best_rank_overall = None

    for entry in rating_changes:
        contest_name = entry['contestName']
        rank = entry['rank']
        new_rating = entry['newRating']
        highest_rating = max(highest_rating, new_rating)

        division = None
        if "Div. 1" in contest_name:
            division = "Div. 1"
        elif "Div. 2" in contest_name:
            division = "Div. 2"
        elif "Div. 3" in contest_name:
            division = "Div. 3"
        else:
            division = "Other"

        if division not in best_rank_by_division or rank < best_rank_by_division[division]:
            best_rank_by_division[division] = rank

        if best_rank_overall is None or rank < best_rank_overall:
            best_rank_overall = rank

    return {
        "total_contests": total_contests,
        "contests_skipped": contests_skipped,
        "best_rank_by_division": best_rank_by_division,
        "highest_rating": highest_rating,
        "best_rank_overall": best_rank_overall,
    }

def get_user_global_country_rank(user_info, rated_users):
    country = user_info.get("country")
    handle = user_info.get("handle")

    global_rank = None
    country_rank = None
    total_users = len(rated_users)
    country_users = [u for u in rated_users if u.get("country") == country]

    for i, u in enumerate(rated_users):
        if u['handle'].lower() == handle.lower():
            global_rank = i + 1
            break

    for i, u in enumerate(country_users):
        if u['handle'].lower() == handle.lower():
            country_rank = i + 1
            break

    global_percentile = round(100 * (1 - (global_rank - 1) / total_users), 2) if global_rank else None
    country_percentile = round(100 * (1 - (country_rank - 1) / len(country_users)), 2) if country_rank else None

    return {
        "global_rank": global_rank,
        "global_percentile": global_percentile,
        "country_rank": country_rank,
        "country_percentile": country_percentile,
        "country": country,
    }

def convert_timestamp(ts):
    if ts is None:
        return "N/A"
    try:
        return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return "N/A"

def safe_get_int(value, default=0):
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except Exception:
        return default

@app.route('/api/stats')
def get_stats():
    handle = request.args.get('handle')
    if not handle:
        return jsonify({"error": "No handle provided"}), 400

    logging.info(f"Request for stats of handle: {handle}")

    user_info_list, err = fetch_user_info(handle)
    if err or not user_info_list:
        return jsonify({"error": f"User info error: {err or 'No user found'}"}), 400

    user_info = user_info_list[0]

    last_online = convert_timestamp(user_info.get("lastOnlineTimeSeconds"))
    member_since = convert_timestamp(user_info.get("registrationTimeSeconds"))

    current_rating = safe_get_int(user_info.get("rating"), default=0)
    max_rating = safe_get_int(user_info.get("maxRating"), default=0)
    current_rank = user_info.get("rank") or "Unrated"
    max_rank = user_info.get("maxRank") or "Unrated"

    submissions, err = fetch_user_submissions(handle)
    if err:
        return jsonify({"error": f"Submissions error: {err}"}), 400

    rating_changes, err = fetch_user_rating(handle)
    if err:
        return jsonify({"error": f"User rating error: {err}"}), 400

    rated_users, err = fetch_rated_users()
    if err:
        rated_users = []

    stats = calculate_stats(submissions)
    contest_stats = analyze_contests(rating_changes)
    rank_stats = get_user_global_country_rank(user_info, rated_users)

    best_contest_position = None
    if rating_changes:
        best_contest_position = min((entry.get('rank', float('inf')) for entry in rating_changes), default=None)
    if best_contest_position is None or best_contest_position == float('inf'):
        best_contest_position = "N/A"

    hacks_successful = user_info.get("successfulHackCount", 0)
    hacks_attempted = user_info.get("hackAttemptCount", 0)

    result = {
        "handle": handle,
        "user_info": {
            "avatar": user_info.get("avatar"),
            "lastOnline": last_online,
            "memberSince": member_since,
            "currentRating": current_rating if current_rating > 0 else "N/A",
            "maxRating": max_rating if max_rating > 0 else "N/A",
            "currentRank": current_rank,
            "maxRank": max_rank,
            "country": user_info.get("country", "N/A"),
            "organization": user_info.get("organization", "N/A"),
            "bestContestPosition": best_contest_position,
            "contestsSkipped": contest_stats.get("contests_skipped", "N/A"),
            "hacksSuccessful": hacks_successful,
            "hacksAttempted": hacks_attempted,
        },
        "stats": stats,
        "contest_stats": contest_stats,
        "rank_stats": rank_stats,
        "error": None,
    }

    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
