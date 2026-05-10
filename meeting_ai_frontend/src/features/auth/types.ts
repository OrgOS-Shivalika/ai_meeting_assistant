export interface OrganizationRef {
  id: string;
  name: string;
  slug: string | null;
}

export interface CurrentUser {
  id: string;
  name: string;
  email: string;
  google_profile_picture: string | null;
  organization: OrganizationRef | null;
}
