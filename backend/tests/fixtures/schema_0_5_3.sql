CREATE TABLE projects (
	id VARCHAR(32) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	niche VARCHAR(200) NOT NULL, 
	language VARCHAR(10) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	current_step VARCHAR(40), 
	video_mode VARCHAR(20) NOT NULL, 
	default_provider VARCHAR(40) NOT NULL, 
	engine_scope VARCHAR(10) NOT NULL, 
	source VARCHAR(10) NOT NULL, 
	planned_for DATETIME, 
	clip JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE providers (
	id VARCHAR(40) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	tier VARCHAR(20) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	is_default BOOLEAN NOT NULL, 
	cost_per_second_usd FLOAT, 
	config JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE settings (
	"key" VARCHAR(100) NOT NULL, 
	value JSON NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY ("key")
);
CREATE TABLE youtube_channels (
	id VARCHAR(32) NOT NULL, 
	channel_id VARCHAR(100) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	is_default BOOLEAN NOT NULL, 
	token_path TEXT NOT NULL, 
	connected_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (channel_id)
);
CREATE TABLE competitors (
	id VARCHAR(32) NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	handle VARCHAR(200) NOT NULL, 
	channel_id VARCHAR(100) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	median_views FLOAT NOT NULL, 
	last_checked_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE music_tracks (
	id VARCHAR(32) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	path TEXT NOT NULL, 
	mood VARCHAR(50) NOT NULL, 
	license VARCHAR(200) NOT NULL, 
	rights_confirmed BOOLEAN NOT NULL, 
	volume FLOAT NOT NULL, 
	is_default BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE source_videos (
	id VARCHAR(32) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	path TEXT NOT NULL, 
	duration_s FLOAT NOT NULL, 
	rights_confirmed BOOLEAN NOT NULL, 
	language VARCHAR(10) NOT NULL, 
	transcript JSON NOT NULL, 
	proposals JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	error TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE pipeline_steps (
	id INTEGER NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	name VARCHAR(40) NOT NULL, 
	position INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	attempts INTEGER NOT NULL, 
	output JSON, 
	error TEXT, 
	started_at DATETIME, 
	finished_at DATETIME, 
	validated_at DATETIME, 
	validated_by VARCHAR(100), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, name), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
CREATE INDEX ix_pipeline_steps_project_id ON pipeline_steps (project_id);
CREATE TABLE ideas (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32), 
	title VARCHAR(200) NOT NULL, 
	hook TEXT NOT NULL, 
	original_angle TEXT NOT NULL, 
	estimated_duration_s FLOAT NOT NULL, 
	potential_score FLOAT NOT NULL, 
	keywords JSON NOT NULL, 
	reuse_risk VARCHAR(10) NOT NULL, 
	visual_style TEXT NOT NULL, 
	sources JSON NOT NULL, 
	selected BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
CREATE INDEX ix_ideas_project_id ON ideas (project_id);
CREATE TABLE competitor_videos (
	id VARCHAR(32) NOT NULL, 
	competitor_id VARCHAR(32) NOT NULL, 
	external_id VARCHAR(100) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	description TEXT NOT NULL, 
	url TEXT NOT NULL, 
	duration_s FLOAT NOT NULL, 
	views INTEGER NOT NULL, 
	published_at DATETIME, 
	ratio FLOAT NOT NULL, 
	outlier BOOLEAN NOT NULL, 
	recipe JSON NOT NULL, 
	source VARCHAR(10) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (competitor_id, external_id), 
	FOREIGN KEY(competitor_id) REFERENCES competitors (id) ON DELETE CASCADE
);
CREATE INDEX ix_competitor_videos_competitor_id ON competitor_videos (competitor_id);
CREATE TABLE social_posts (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	caption TEXT NOT NULL, 
	scheduled_at DATETIME, 
	method VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	external_id VARCHAR(200), 
	error TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, platform), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);
CREATE INDEX ix_social_posts_project_id ON social_posts (project_id);
CREATE TABLE scripts (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	idea_id VARCHAR(32), 
	version INTEGER NOT NULL, 
	hook TEXT NOT NULL, 
	body TEXT NOT NULL, 
	conclusion TEXT NOT NULL, 
	call_to_action TEXT NOT NULL, 
	estimated_duration_s FLOAT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(idea_id) REFERENCES ideas (id) ON DELETE SET NULL
);
CREATE INDEX ix_scripts_project_id ON scripts (project_id);
CREATE TABLE scenes (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	script_id VARCHAR(32), 
	position INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	visual_prompt TEXT NOT NULL, 
	negative_prompt TEXT NOT NULL, 
	transition VARCHAR(40) NOT NULL, 
	duration_s FLOAT NOT NULL, 
	importance VARCHAR(20) NOT NULL, 
	provider_id VARCHAR(40), 
	provider_locked BOOLEAN NOT NULL, 
	provider_reason TEXT NOT NULL, 
	estimated_cost_usd FLOAT NOT NULL, 
	seed INTEGER, 
	image_status VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(script_id) REFERENCES scripts (id) ON DELETE CASCADE, 
	FOREIGN KEY(provider_id) REFERENCES providers (id)
);
CREATE INDEX ix_scenes_project_id ON scenes (project_id);
CREATE TABLE assets (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	scene_id VARCHAR(32), 
	kind VARCHAR(20) NOT NULL, 
	path TEXT NOT NULL, 
	mime_type VARCHAR(100) NOT NULL, 
	origin VARCHAR(20) NOT NULL, 
	license VARCHAR(100) NOT NULL, 
	rights_confirmed BOOLEAN NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(scene_id) REFERENCES scenes (id) ON DELETE SET NULL
);
CREATE INDEX ix_assets_project_id ON assets (project_id);
CREATE TABLE voice_takes (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	script_id VARCHAR(32), 
	engine VARCHAR(20) NOT NULL, 
	voice_gender VARCHAR(10) NOT NULL, 
	language VARCHAR(10) NOT NULL, 
	speed FLOAT NOT NULL, 
	pitch FLOAT NOT NULL, 
	emotion VARCHAR(30) NOT NULL, 
	pauses JSON NOT NULL, 
	asset_id VARCHAR(32), 
	selected BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(script_id) REFERENCES scripts (id) ON DELETE SET NULL, 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE SET NULL
);
CREATE INDEX ix_voice_takes_project_id ON voice_takes (project_id);
CREATE TABLE renders (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	codec VARCHAR(20) NOT NULL, 
	asset_id VARCHAR(32), 
	status VARCHAR(20) NOT NULL, 
	approved_at DATETIME, 
	approved_by VARCHAR(100), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE SET NULL
);
CREATE INDEX ix_renders_project_id ON renders (project_id);
CREATE TABLE provider_jobs (
	id VARCHAR(32) NOT NULL, 
	provider_id VARCHAR(40) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	scene_id VARCHAR(32), 
	operation VARCHAR(40) NOT NULL, 
	external_id VARCHAR(200), 
	status VARCHAR(20) NOT NULL, 
	params JSON NOT NULL, 
	estimated_cost_usd FLOAT NOT NULL, 
	result_asset_id VARCHAR(32), 
	error TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(provider_id) REFERENCES providers (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(scene_id) REFERENCES scenes (id) ON DELETE SET NULL, 
	FOREIGN KEY(result_asset_id) REFERENCES assets (id) ON DELETE SET NULL
);
CREATE INDEX ix_provider_jobs_project_id ON provider_jobs (project_id);
CREATE INDEX ix_provider_jobs_provider_id ON provider_jobs (provider_id);
CREATE TABLE subtitles (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	voice_take_id VARCHAR(32), 
	segments JSON NOT NULL, 
	style JSON NOT NULL, 
	position VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(voice_take_id) REFERENCES voice_takes (id) ON DELETE SET NULL
);
CREATE INDEX ix_subtitles_project_id ON subtitles (project_id);
CREATE TABLE costs (
	id INTEGER NOT NULL, 
	project_id VARCHAR(32), 
	scene_id VARCHAR(32), 
	provider_id VARCHAR(40), 
	provider_job_id VARCHAR(32), 
	amount_usd FLOAT NOT NULL, 
	kind VARCHAR(15) NOT NULL, 
	description TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE SET NULL, 
	FOREIGN KEY(scene_id) REFERENCES scenes (id) ON DELETE SET NULL, 
	FOREIGN KEY(provider_id) REFERENCES providers (id), 
	FOREIGN KEY(provider_job_id) REFERENCES provider_jobs (id) ON DELETE SET NULL
);
CREATE INDEX ix_costs_project_id ON costs (project_id);
CREATE INDEX ix_costs_created_at ON costs (created_at);
CREATE TABLE publish_jobs (
	id VARCHAR(32) NOT NULL, 
	project_id VARCHAR(32) NOT NULL, 
	render_id VARCHAR(32), 
	channel_id VARCHAR(32), 
	title VARCHAR(100) NOT NULL, 
	description TEXT NOT NULL, 
	tags JSON NOT NULL, 
	privacy VARCHAR(10) NOT NULL, 
	made_for_kids BOOLEAN NOT NULL, 
	category_id VARCHAR(5) NOT NULL, 
	scheduled_at DATETIME, 
	ai_disclosure BOOLEAN NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	human_approved_at DATETIME, 
	human_approved_by VARCHAR(100), 
	youtube_video_id VARCHAR(50), 
	error TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(render_id) REFERENCES renders (id) ON DELETE SET NULL, 
	FOREIGN KEY(channel_id) REFERENCES youtube_channels (id) ON DELETE SET NULL
);
CREATE INDEX ix_publish_jobs_project_id ON publish_jobs (project_id);
CREATE TABLE analytics (
	id INTEGER NOT NULL, 
	publish_job_id VARCHAR(32), 
	youtube_video_id VARCHAR(50) NOT NULL, 
	views INTEGER NOT NULL, 
	likes INTEGER NOT NULL, 
	comments INTEGER NOT NULL, 
	average_view_duration_s FLOAT NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	project_id VARCHAR(32), 
	source VARCHAR(10) NOT NULL, 
	collected_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(publish_job_id) REFERENCES publish_jobs (id) ON DELETE CASCADE, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE SET NULL
);
CREATE INDEX ix_analytics_publish_job_id ON analytics (publish_job_id);
CREATE INDEX ix_analytics_youtube_video_id ON analytics (youtube_video_id);
