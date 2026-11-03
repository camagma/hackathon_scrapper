# Devpost listing data

## Source and scope

Inspected on November 2, 2026:

```text
GET https://devpost.com/api/hackathons?page=1
```

The endpoint returned HTTP 200 with `application/json; charset=utf-8`. It is an unofficial public endpoint and may change without notice.

The [original saved response](../inspection/response.json) contains nine records. All nine have `open_state: "open"`. A separate [upcoming snapshot](../inspection/upcoming.json) contains nine upcoming records.

The listing HTML returned HTTP 403 to a direct request. The page was accessible through a separate web tool, but no browser network trace was captured to establish how the current frontend calls this endpoint. The JSON schema below comes from the direct endpoint response.

## Response structure

The root contains `hackathons`, an array of records, and `meta`:

```json
{
  "total_count": 14229,
  "per_page": 9,
  "fuzzy": false
}
```

These metadata values describe the saved response, not fixed API guarantees.

| Field | Observed type and example |
| --- | --- |
| `id` | Integer: `31302` |
| `title` | String: `PayPal AI Hackathon` |
| `url` | String: `https://paypalaihackathon.devpost.com/` |
| `displayed_location` | Object: `{"icon": "globe", "location": "Online"}` |
| `open_state` | String: `open` or `upcoming` in the filtered samples |
| `submission_period_dates` | String: `Oct 01 - Nov 12, 2026` |
| `time_left_to_submission` | Approximate text: `10 days left` or `about 1 month left` |
| `themes` | Array of `{id, name}` objects; `Machine Learning/AI` has ID `6` |
| `prize_amount` | HTML string: `$<span data-currency-value>67,500</span>` |
| `prizes_counts` | Object with integer `cash` and `other` values |
| `registrations_count` | Integer participant registration count |
| `organization_name` | String |
| `featured` | Boolean |
| `winners_announced` | Boolean |
| `invite_only` | Boolean |
| `managed_by_devpost_badge` | Boolean |
| `eligibility_requirement_invite_only_description` | `null` in all sampled records |
| `thumbnail_url` | String; may be a protocol-relative URL |
| `analytics_identifier` | String |
| `submission_gallery_url` | String URL |
| `start_a_submission_url` | String URL |

## Date handling

No separate registration deadline appears in the sampled records. `registrations_count` is a count, not a date.

The submission start and end dates must be parsed from `submission_period_dates`; separate structured date fields are absent. No exact time or timezone is provided. Opening reminders use the start date for upcoming events. The end date remains the **submission deadline** for reference and CSV exports. Neither date is a separate registration deadline; both retain calendar-date precision.

`time_left_to_submission` is approximate display text and must not be used to calculate a deadline. Prize values contain HTML and require text extraction before display or CSV export.

Additional observed date formats include `Nov 09 - 30, 2026`, `Dec 19, 2026 - Jan 18, 2027`, and the single date `Dec 31, 2026`. The parser stores ISO calendar dates alongside the original period. A single-day event has identical start and deadline dates. When the start year is omitted, it is inherited from the end year; a December-to-January range uses the preceding start year. Invalid dates, reversed ranges, and unknown formats stop the sync before any database changes.

## Verified listing parameters

Follow-up requests on the same date confirmed:

| Parameter | Observed behavior |
| --- | --- |
| `status[]=open` | 45 online records reported |
| `status[]=upcoming` | 34 online records reported; returned state is `upcoming` |
| Repeated `status[]` values | Open and upcoming are combined with OR; 79 records reported |
| `challenge_type[]=online` | Filtered records have `displayed_location.location` equal to `Online` |
| `per_page=100` | Server caps the reported page size at 40 |
| `page=1`, `page=2` with `per_page=40` | Complete combined listing returned as 40 + 39 records |

These counts are observations, not constants. The client requests 40 items and follows the reported total until all unique IDs have been collected, within its page limit. Local filters validate online status and event state again. Theme and keyword parameters are not sent to the server.

## Access policy

The [saved robots.txt](../inspection/robots.txt) has an empty `Disallow` for `User-agent: *`, allowing the listing path for this project's User-Agent at inspection time. It separately disallows BLEXBot, Omgilibot, Omgili, ImagesiftBot, and Bytespider. Robots rules do not guarantee API availability.

Inspection made three direct requests: robots.txt, the listing HTML, and one JSON page. No project pages or participant profiles were fetched.

The follow-up fetch implementation was verified with the parameters above and a complete live run (one robots.txt request and two listing pages). No individual event, project, or profile pages were accessed.

The JSON listing provides multiple events per request, reducing server load and avoiding individual page scraping. The inspection script checks robots.txt before a live fetch, uses timeouts, and stops on HTTP errors, including 403 and 429.

## Reproduce

From the repository root:

```sh
python scripts/inspect_endpoint.py --offline inspection/response.json
```

For a fresh snapshot:

```sh
python scripts/inspect_endpoint.py
```

The script prints the first three records without modifying their fields, followed by the union of observed field names.
