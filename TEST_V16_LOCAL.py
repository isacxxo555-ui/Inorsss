"""Static validation for InveNOIR v16; does not import Discord or connect to a server."""
import ast
from pathlib import Path
root=Path(__file__).resolve().parent
src=root/'InveNOIR_Chorus_Battle_Bot_v16.py'
s=src.read_text(encoding='utf-8')
ast.parse(s)
assert 'VERSION = "v16.0-20261111-group-finder-profile-dashboard"' in s
assert 'set(COMPETITORS | MODERATORS)' in s
assert 'class TeamBrowseView(discord.ui.View)' in s
assert 'class ProfileBrowseView(discord.ui.View)' in s
assert 'class TeamFinderPanelView(discord.ui.View)' in s
assert 'async def create_team_application' in s
assert 'async def process_team_application_decision' in s
assert 'async def ensure_private_team_channel' in s
assert 'client.tree.remove_command(_retired_command, guild=TARGET_GUILD)' in s
for name in ('registration_panel','team_registrations','team_registration_sync','my_team_registration'):
    assert f'"{name}"' in s
assert 'Team Chat หลังหัวหน้าทีมตอบรับเท่านั้น' in s
assert 'INVENOIR_DATA_DIR' in s
assert (root/'START_V16.bat').exists()
assert (root/'README_TH_V16.txt').exists()
print('[InveNOIR] v16 static validation OK')
