import streamlit as st
import requests
import pandas as pd
import time
import re
import io

st.set_page_config(page_title="LinkedIn Posts Fetcher", layout="wide")

def get_profile_name_from_url(linkedin_url):
    """Helper to extract a profile name/id from URL for display and filename."""
    if not linkedin_url:
        return "UnknownProfile"
    match_in = re.search(r'/in/([^/]+)', linkedin_url)
    if match_in:
        return match_in.group(1)
    match_company = re.search(r'/company/([^/]+)', linkedin_url)
    if match_company:
        return match_company.group(1)
    return "UnknownProfile"

def fetch_all_posts(profile_url, api_key, max_pages, post_type):
    """
    Fetches all posts for a given LinkedIn profile or company URL, handling pagination up to max_pages.
    """
    all_posts_data = []
    current_pagination_token = None
    page_count = 0
    
    # Set API URL based on post_type
    if post_type == "Company Posts":
        API_URL = "https://fresh-linkedin-profile-data.p.rapidapi.com/get-company-posts"
    else:
        API_URL = "https://fresh-linkedin-profile-data.p.rapidapi.com/get-profile-posts"
    
    _headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "fresh-linkedin-profile-data.p.rapidapi.com"
    }

    progress_bar = st.progress(0)
    status_text = st.empty()

    while page_count < max_pages:
        page_count += 1
        status_text.text(f"Fetching page {page_count} of {max_pages} for {profile_url}...")
        progress_bar.progress(min(page_count / max_pages, 1.0))

        querystring = {
            "linkedin_url": profile_url,
            "type": "posts"
        }
        if current_pagination_token:
            querystring["pagination_token"] = current_pagination_token

        try:
            response = requests.get(API_URL, headers=_headers, params=querystring, timeout=30)
            response.raise_for_status()
            json_response = response.json()
        except requests.exceptions.Timeout:
            st.warning("Request timed out. Retrying after a short delay...")
            time.sleep(10)
            continue
        except requests.exceptions.RequestException as e:
            st.error(f"Error during API request: {e}")
            break
        except ValueError as e:
            st.error(f"Error decoding JSON response: {e}")
            break

        api_message = json_response.get('message', 'Unknown error from API')
        if api_message.lower() != "ok":
            st.warning(f"API Alert: {api_message}")
            if "rate limit" in api_message.lower():
                st.warning("Rate limit likely exceeded. Waiting for 60 seconds before retrying...")
                time.sleep(60)
                continue

            stop_messages = ["profile not found", "profile is private", "could not find linkedin profile", "company not found"]
            if any(stop_msg in api_message.lower() for stop_msg in stop_messages):
                st.error(f"Stopping pagination for {profile_url} due to: {api_message}")
                break

            if page_count > 1 and not json_response.get("data"):
                st.warning("API error on subsequent page with no data, assuming end of valid pages.")
                break
            break

        posts_on_page = json_response.get("data", [])
        
        if not posts_on_page:
            if page_count > 1 or all_posts_data:
                st.info("No more posts found on this page (or empty data array).")
            else:
                st.warning(f"No posts found on the first page for {profile_url}. Profile or company might be empty or there's an issue.")
            break 

        all_posts_data.extend(posts_on_page)
        st.info(f"Found {len(posts_on_page)} posts on page {page_count}.")

        paging_info = json_response.get("paging", {})
        current_pagination_token = paging_info.get("pagination_token")

        if not current_pagination_token:
            st.info("No more pagination token. Reached the end of posts.")
            break
        
        time.sleep(1.5)

    progress_bar.empty()
    status_text.empty()
    return all_posts_data

def process_posts_for_excel(raw_posts_data, queried_profile_url):
    """
    Processes the raw post data into a list of dictionaries suitable for an Excel sheet.
    """
    processed_data = []
    queried_profile_name = get_profile_name_from_url(queried_profile_url)

    for post in raw_posts_data:
        if not isinstance(post, dict):
            st.warning(f"Skipping non-dictionary item in posts data: {post}")
            continue

        poster_info = post.get("poster", {}) or {}
        image_urls_list = post.get("images", []) or []
        image_urls = [img.get("url") for img in image_urls_list if isinstance(img, dict) and img.get("url")]
        video_info = post.get("video", {}) or {}
        document_info = post.get("document", {}) or {}
        repost_stats_info = post.get("repost_stats", {}) or {}

        post_type_display = "Original Post"
        original_content_urn_if_reshared = None
        if post.get("reshared"):
            post_type_display = f"Reshare by {queried_profile_name}"
            original_content_urn_if_reshared = post.get("urn")

        author_first_name = poster_info.get("first")
        author_last_name = poster_info.get("last")
        author_headline = poster_info.get("headline")
        author_public_id = poster_info.get("public_id")
        author_linkedin_url = post.get("poster_linkedin_url")

        if not (author_first_name or author_last_name) and author_linkedin_url:
            author_display_name_from_url = get_profile_name_from_url(author_linkedin_url)
            if author_display_name_from_url != "UnknownProfile":
                author_first_name = author_display_name_from_url
            if not author_headline and "company" in (author_linkedin_url or ""):
                author_headline = "Company Page"

        activity_urn_str = None
        post_url_val = post.get("post_url")
        if post_url_val and "urn:li:activity:" in post_url_val:
            try:
                activity_urn_str = post_url_val.split("urn:li:activity:")[-1].split("/")[0]
            except IndexError:
                pass
        
        if post.get("reshared") and post.get("repost_urn") and not activity_urn_str:
            activity_urn_str = post.get("repost_urn")

        record = {
            "Post Type": post_type_display,
            "Content Author Name": (author_first_name or '') + ' ' + (author_last_name or ''),
            "Content Author Headline": author_headline,
            "Content Text (Original or Shared)": post.get("text"),
            "Resharer Comment (by Queried Profile)": post.get("resharer_comment") if post.get("reshared") else None,
            "Time Ago": post.get("time"),
            "Engagement Likes (on this item)": post.get("num_likes"),
            "Engagement Comments (on this item)": post.get("num_comments"),
            "Engagement Reactions (on this item)": post.get("num_reactions"),
            "Engagement Reposts (of this item)": post.get("num_reposts"),
            "Engagement Appreciations": post.get("num_appreciations"),
            "Engagement Empathy": post.get("num_empathy"),
            "Engagement Entertainments": post.get("num_entertainments"),
            "Engagement Interests": post.get("num_interests"),
            "Engagement Praises": post.get("num_praises"),
            "Image URLs": "\n".join(image_urls) if image_urls else None,
            "Video URL": video_info.get("stream_url"),
            "Video Duration (ms)": video_info.get("duration"),
            "Document Title": document_info.get("title"),
            "Document URL": document_info.get("url"),
            "Document Page Count": document_info.get("page_count"),
            "Article Title": post.get("article_title"),
            "Article Subtitle": post.get("article_subtitle"),
            "Article Target URL": post.get("article_target_url"),
            "Article Description": post.get("article_description"),
            "Original Post Likes (if Reshared)": repost_stats_info.get("num_likes") if post.get("reshared") else None,
            "Original Post Comments (if Reshared)": repost_stats_info.get("num_comments") if post.get("reshared") else None,
            "Original Post Reactions (if Reshared)": repost_stats_info.get("num_reactions") if post.get("reshared") else None,
            "Original Post Reposts (if Reshared)": repost_stats_info.get("num_reposts") if post.get("reshared") else None,
            "Original Post Appreciations (if Reshared)": repost_stats_info.get("num_appreciations") if post.get("reshared") else None,
            "Original Post Interests (if Reshared)": repost_stats_info.get("num_interests") if post.get("reshared") else None,
            "Original Post Praises (if Reshared)": repost_stats_info.get("num_praises") if post.get("reshared") else None,
        }
        processed_data.append(record)
    return processed_data

# Sidebar inputs
st.sidebar.header("LinkedIn Posts Fetcher")
api_key = st.sidebar.text_input("RapidAPI Key", type="password")
linkedin_url = st.sidebar.text_input("LinkedIn Profile or Company URL")
post_type = st.sidebar.radio("Select Post Type", ["Profile Posts", "Company Posts"])
max_pages = st.sidebar.number_input("Number of Pages to Fetch", min_value=1, max_value=50, value=1)

# Main content
st.title("LinkedIn Posts Fetcher")
st.markdown("Enter your RapidAPI key, LinkedIn profile or company URL, select the post type, and the number of pages to fetch in the sidebar (1 page gives you ~50 posts), then click the button below to fetch posts.")

if st.button("Fetch Posts"):
    if not api_key:
        st.error("Please enter a valid RapidAPI key.")
    elif not linkedin_url or not linkedin_url.startswith("https://www.linkedin.com/"):
        st.error("Please enter a valid LinkedIn profile or company URL.")
    else:
        with st.spinner(f"Fetching {post_type.lower()}..."):
            all_raw_posts = fetch_all_posts(linkedin_url, api_key, max_pages, post_type)

        if all_raw_posts:
            st.success(f"Fetched a total of {len(all_raw_posts)} post items.")
            excel_data = process_posts_for_excel(all_raw_posts, linkedin_url)

            if excel_data:
                df = pd.DataFrame(excel_data)
                st.dataframe(df, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False)
                excel_data = output.getvalue()
                
                profile_name = get_profile_name_from_url(linkedin_url)
                st.download_button(
                    label="Download Excel File",
                    data=excel_data,
                    file_name=f"{profile_name}_linkedin_{post_type.lower().replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.error("No data was processed into the Excel format. Raw posts might have been empty or unprocessable.")
        else:
            st.error(f"No {post_type.lower()} were fetched for {linkedin_url}. The profile or company might be empty, private, or an API issue occurred.")
