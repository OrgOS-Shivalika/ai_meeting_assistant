# Meeting Types Feature Architecture
Version: v1

---

# Feature Goal

The Meeting Types feature organizes meetings into structured categories and teams.

Flow:

```text
Meeting Types
    ↓
Teams
    ↓
Meetings
    ↓
Meeting Details
```

Example:

```text
Customer Development
    └── Enterprise Clients
            └── Weekly Feedback Meeting
```

---

# Core Concepts

---

## 1. Meeting Types

High-level meeting categories.

Examples:

- Engineering
- Marketing
- Hiring
- Customer Development

---

## 2. Teams

Groups inside meeting types.

Examples:

Inside "Engineering":

- Frontend Team
- Backend Team
- DevOps Team

---

## 3. Meetings

Actual meetings belonging to teams.

Meetings can be:

- scheduled
- live
- completed
- uncategorized

---

# Uncategorized Meetings

A meeting without a team:

```sql
team_id IS NULL
```

These meetings appear in:

```text
Uncategorized
```

---

# DATABASE ARCHITECTURE

---

# Existing Tables

Already available:

```text
users
meetings
```

---

# Existing meetings Table

Current structure:

```text
meetings
├── id
├── meeting_url
├── bot_id
├── status
├── summary
├── transcript_raw
├── transcript_text
├── title
├── user_id
├── google_event_id
├── google_event_data
├── transcript
├── created_at
└── updated_at
```

This table remains the core table.

We only extend it.

---

# DATABASE RELATIONSHIP DIAGRAM

```text
users
    └── meeting_types
            └── teams
                    └── meetings
                            ├── meeting_participants
                            ├── meeting_notes
                            ├── meeting_assets
                            └── meeting_events
```

---

# TABLES

---

# 1. meeting_types

Stores top-level categories.

---

## SQL

```sql
CREATE TABLE meeting_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    user_id UUID NOT NULL
    REFERENCES users(id)
    ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,

    description TEXT,

    color VARCHAR(50),

    icon VARCHAR(100),

    created_at TIMESTAMP DEFAULT NOW(),

    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

# meeting_types Rules

---

## Unique Per User

A user cannot create duplicate names.

Recommended unique constraint:

```sql
CREATE UNIQUE INDEX idx_unique_meeting_type
ON meeting_types(user_id, name);
```

---

# 2. teams

Stores operational groups inside meeting types.

---

## SQL

```sql
CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    meeting_type_id UUID NOT NULL
    REFERENCES meeting_types(id)
    ON DELETE CASCADE,

    user_id UUID NOT NULL
    REFERENCES users(id)
    ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,

    description TEXT,

    created_at TIMESTAMP DEFAULT NOW(),

    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

# Teams Rules

---

## Team belongs to ONE meeting type

```text
1 team → 1 meeting type
```

---

## Meeting type can contain MANY teams

```text
1 meeting type → many teams
```

---

# 3. meetings (MODIFICATIONS)

Existing table should be extended.

---

## Add team relation

```sql
ALTER TABLE meetings
ADD COLUMN team_id UUID REFERENCES teams(id) ON DELETE SET NULL;
```

---

## Add scheduling fields

```sql
ALTER TABLE meetings
ADD COLUMN scheduled_at TIMESTAMP;

ALTER TABLE meetings
ADD COLUMN started_at TIMESTAMP;

ALTER TABLE meetings
ADD COLUMN ended_at TIMESTAMP;

ALTER TABLE meetings
ADD COLUMN duration_minutes INT;
```

---

## Add platform metadata

```sql
ALTER TABLE meetings
ADD COLUMN meeting_platform VARCHAR(100);
```

Examples:

- google_meet
- zoom
- teams

---

# Meeting Rules

---

## Meeting belongs to ONE team

```text
1 meeting → 1 team
```

---

## Team can contain MANY meetings

```text
1 team → many meetings
```

---

## Uncategorized meetings

```sql
team_id IS NULL
```

---

# OPTIONAL TABLES (Recommended)

These are not required immediately but strongly recommended.

---

# 4. meeting_participants

Tracks attendees.

---

## SQL

```sql
CREATE TABLE meeting_participants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    meeting_id INT NOT NULL
    REFERENCES meetings(id)
    ON DELETE CASCADE,

    participant_name VARCHAR(255),

    participant_email VARCHAR(255),

    joined_at TIMESTAMP,

    left_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW()
);
```

---

# 5. meeting_notes

Stores AI/manual notes.

---

## SQL

```sql
CREATE TABLE meeting_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    meeting_id INT NOT NULL
    REFERENCES meetings(id)
    ON DELETE CASCADE,

    note_type VARCHAR(100),

    content TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT NOW(),

    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

# 6. meeting_assets

Stores recordings/files/transcripts.

---

## SQL

```sql
CREATE TABLE meeting_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    meeting_id INT NOT NULL
    REFERENCES meetings(id)
    ON DELETE CASCADE,

    asset_type VARCHAR(100),

    file_url TEXT,

    mime_type VARCHAR(255),

    created_at TIMESTAMP DEFAULT NOW()
);
```

---

# 7. meeting_events

Tracks lifecycle events.

Useful for debugging + analytics.

---

## SQL

```sql
CREATE TABLE meeting_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    meeting_id INT NOT NULL
    REFERENCES meetings(id)
    ON DELETE CASCADE,

    event_type VARCHAR(100),

    metadata JSONB,

    created_at TIMESTAMP DEFAULT NOW()
);
```

---

# INDEXES

---

# meeting_types

```sql
CREATE INDEX idx_meeting_types_user
ON meeting_types(user_id);
```

---

# teams

```sql
CREATE INDEX idx_teams_meeting_type
ON teams(meeting_type_id);

CREATE INDEX idx_teams_user
ON teams(user_id);
```

---

# meetings

```sql
CREATE INDEX idx_meetings_team
ON meetings(team_id);

CREATE INDEX idx_meetings_user
ON meetings(user_id);

CREATE INDEX idx_meetings_status
ON meetings(status);

CREATE INDEX idx_meetings_scheduled_at
ON meetings(scheduled_at);
```

---

# API ARCHITECTURE

---

# API BASE

```text
/api/v1
```

---

# MEETING TYPES APIs

---

# Create Meeting Type

```http
POST /api/v1/meeting-types
```

---

## Request

```json
{
  "name": "Engineering",
  "description": "Engineering related meetings",
  "color": "#6366F1",
  "icon": "code"
}
```

---

## Response

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "name": "Engineering"
  }
}
```

---

# Get All Meeting Types

```http
GET /api/v1/meeting-types
```

---

# Get Single Meeting Type

```http
GET /api/v1/meeting-types/:meetingTypeId
```

---

# Update Meeting Type

```http
PATCH /api/v1/meeting-types/:meetingTypeId
```

---

# Delete Meeting Type

```http
DELETE /api/v1/meeting-types/:meetingTypeId
```

---

# TEAMS APIs

---

# Create Team

```http
POST /api/v1/meeting-types/:meetingTypeId/teams
```

---

## Request

```json
{
  "name": "Frontend Team",
  "description": "Frontend engineering team"
}
```

---

# Get Teams By Meeting Type

```http
GET /api/v1/meeting-types/:meetingTypeId/teams
```

---

# Get Single Team

```http
GET /api/v1/teams/:teamId
```

---

# Update Team

```http
PATCH /api/v1/teams/:teamId
```

---

# Delete Team

```http
DELETE /api/v1/teams/:teamId
```

---

# MEETINGS APIs

---

# Create Meeting

```http
POST /api/v1/teams/:teamId/meetings
```

---

# Create Uncategorized Meeting

```http
POST /api/v1/meetings
```

Without `team_id`.

---

# Get Team Meetings

```http
GET /api/v1/teams/:teamId/meetings
```

---

# Get Uncategorized Meetings

```http
GET /api/v1/meetings/uncategorized
```

---

# Get Single Meeting

```http
GET /api/v1/meetings/:meetingId
```

---

# Update Meeting

```http
PATCH /api/v1/meetings/:meetingId
```

---

# Delete Meeting

```http
DELETE /api/v1/meetings/:meetingId
```

---

# Schedule Meeting

```http
POST /api/v1/teams/:teamId/meetings/schedule
```

---

## Request

```json
{
  "title": "Weekly Engineering Sync",
  "scheduled_at": "2026-05-10T14:00:00Z",
  "meeting_platform": "google_meet"
}
```

---

# Meeting Details APIs

---

# Get Meeting Transcript

```http
GET /api/v1/meetings/:meetingId/transcript
```

---

# Get Meeting Summary

```http
GET /api/v1/meetings/:meetingId/summary
```

---

# Get Meeting Participants

```http
GET /api/v1/meetings/:meetingId/participants
```

---

# FUTURE APIs

Not needed immediately.

---

## AI APIs

```text
/ask
/summarize
/action-items
/decisions
/search
```

---

## Analytics APIs

```text
/analytics
/insights
/meeting-stats
```

---

# FRONTEND FLOW

---

# Sidebar

```text
Meeting Types
```

---

# User Flow

```text
Meeting Types
    ↓
Teams
    ↓
Meetings
    ↓
Meeting Details
```

---

# Meeting Details Page

Should include:

```text
- transcript
- summary
- participants
- notes
- recording
- AI insights
```

---

# RECOMMENDED DEVELOPMENT ORDER

---

## Phase 1

```text
meeting_types
teams
meetings relation
```

---

## Phase 2

```text
meeting scheduling
```

---

## Phase 3

```text
participants
notes
assets
events
```

---

# IMPORTANT FUTURE NOTE

Current:

```text
meetings.id = INT
users.id = UUID
```

This mismatch should eventually be migrated.

But NOT now.

Avoid breaking current production flow.