import os

def narrate(decision: dict, pr: dict) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return decision.get("rationale", "")
    try:
        from groq import Groq
        client = Groq(api_key=key)
        prompt = f"""Summarize this code review decision in 2 sentences.
PR: {pr['title']} by {pr['author']}
Top reviewers: {[r['login'] for r in decision['reviewers']]}
Risk flags: {decision['risk_flags']}
Shared files: {decision['reviewers'][0]['shared_files'] if decision['reviewers'] else 0}
Be specific about why these reviewers were chosen."""
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        return r.choices[0].message.content
    except Exception:
        return decision["rationale"]