export interface Task {
  id: number;
  task: string;
  owner: string;
  priority: 'low' | 'medium' | 'high';
  due_date: string | null;
  is_completed: boolean;
  created_at: string;
  updated_at: string;
}

export interface Participant {
  id: number;
  name: string;
  email: string | null;
  is_organizer: string;
  avatar_url: string | null;
  created_at: string;
}

export interface Team {
  id: number;
  category_id: number;
  name: string;
  created_at?: string;
}

export interface Category {
  id: number;
  name: string;
  color?: string | null;
  created_at?: string;
  teams?: Team[];
}

export interface MeetingCategoryRef {
  id: number;
  name: string;
  color?: string | null;
}

export interface MeetingTeamRef {
  id: number;
  name: string;
  category_id: number;
}

export interface Meeting {
  id: number;
  meeting_url: string;
  title: string;
  summary: string;
  status: string;
  created_at: string;
  updated_at: string;
  transcript_text?: string;
  transcript_raw?: any;
  tasks?: Task[];
  participants?: Participant[];
  category?: MeetingCategoryRef | null;
  team?: MeetingTeamRef | null;
}
