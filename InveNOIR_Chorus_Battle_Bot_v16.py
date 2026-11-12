# -*- coding: utf-8 -*-
"""InveNOIR Chorus Battle bot v16: redesigned Group Finder, member profiles, safety, notifications and acceptance-based team chat."""
import asyncio
import os
import sys
import traceback
import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Literal
from urllib.parse import urlparse

VERSION = "v16.0-20261111-group-finder-profile-dashboard"

# Print the actual executable path FIRST. This makes stale files easy to identify.
print(f"[InveNOIR] RUNNING {VERSION}", flush=True)
print(f"[InveNOIR] FILE: {Path(__file__).resolve()}", flush=True)

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=ROOT / ".env")
DATA_DIR = Path(os.getenv("INVENOIR_DATA_DIR", str(ROOT))).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
GUILD_ID_RAW = os.getenv("DISCORD_GUILD_ID", "").strip()
if not TOKEN or not GUILD_ID_RAW.isdigit():
    raise SystemExit("[ERROR] Please fill DISCORD_BOT_TOKEN and numeric DISCORD_GUILD_ID in .env")
GUILD_ID = int(GUILD_ID_RAW)
TARGET_GUILD = discord.Object(id=GUILD_ID)

ROLE_CONFIG = [
    ("Organizer", 0xED6174), ("Staff", 0xE7AD52), ("Judge", 0xB583EB),
    ("Team Leader", 0x5A9FE9), ("Vocalist", 0xE985B4), ("VTuber", 0xB89BEC),
    ("Mixer", 0x70B9D8), ("Artist", 0x72C9A0), ("Animator", 0xDC9D69),
    ("Audience", 0x9CA3AF),
]

SECTIONS = [
    ("✧ Welcome", [
        ("text", "👋・welcome", "ยินดีต้อนรับสู่ InveNOIR Chorus Battle"),
        ("text", "📢・announcements", "ประกาศสำคัญและข่าวสารการแข่งขัน"),
        ("text", "📜・rules", "กฎการแข่งขันและกฎเซิร์ฟเวอร์"),
        ("text", "📌・information", "รูปแบบการแข่งขันและรางวัล"),
        ("text", "🎭・choose-your-role", "กดรับยศที่นี่ก่อนเริ่มใช้งาน"),
        ("text", "🙋・introduce-yourself", "แนะนำตัวหลังจากได้รับยศ"),
    ]),
    ("✧ Chorus Battle", [
        ("text", "🎭・themes", "ธีมการแข่งขัน: Origin, The Crisis และรอบสุดท้าย"),
        ("text", "📅・schedule", "ตารางการแข่งขันและกำหนดส่งผลงาน"),
        ("text", "📝・registration", "ข้อมูลการสมัครแข่งขัน"),
        ("text", "🏆・results", "ประกาศผลการแข่งขัน"),
        ("text", "❓・questions", "สอบถามเรื่องการแข่งขัน"),
    ]),
    ("✧ Team Finder", [
        ("forum", "🔎・group-finder", "ประกาศหาทีมและหาสมาชิกทุกสายงาน"),
        ("text", "👤・member-profiles", "สร้างโปรไฟล์ ใส่นามแฝงและลิงก์ผลงาน เพื่อให้ทีมค้นหาคนที่กำลังหาทีม"),
        ("text", "💬・team-chat", "แชทพูดคุยรวมของสมาชิกทุกสายงาน"),
    ]),
    ("✧ Community", [
        ("text", "💬・general-chat", "พูดคุยทั่วไป"),
        ("forum", "🎶・share-your-work", "โชว์ผลงานร้องเพลง ภาพวาด และ Animator"),
        ("text", "📷・media", "แชร์รูปภาพและสื่อ"),
        ("text", "🤖・bot-commands", "ใช้คำสั่งบอท"),
    ]),
    ("✧ Voice Channels", [
        ("voice", "🔊 General Lounge", None),
        ("voice", "🎙️ Team Meeting 1", None),
        ("voice", "🎙️ Team Meeting 2", None),
    ]),
    ("✧ Staff Only 🔒", [
        ("text", "💼・staff-chat", "สำหรับทีมงาน"),
        ("text", "📋・applications-review", "ตรวจใบสมัคร"),
        ("text", "⚖️・judging-room", "ห้องกรรมการ"),
        ("text", "🗃️・submissions", "ตรวจผลงาน"),
        ("text", "📣・staff-announcements", "ข่าวสารทีมงาน"),
    ]),
]

# These categories are readonly for members; moderators/admins can still write.
READ_ONLY_CHANNELS = {
    "👋・welcome", "📢・announcements", "📜・rules", "📌・information", "🎭・choose-your-role",
    "🎭・themes", "📅・schedule", "📝・registration", "🏆・results",
}


class SetupClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())  # no Message Content intent needed
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(SelfRoleView())  # Keep self-role panel alive after bot restarts.
        register_team_finder_views(self)  # Persistent Team Finder controls and pending application/invitation buttons.
        if not announcement_worker.is_running():
            announcement_worker.start()
        commands = await self.tree.sync(guild=TARGET_GUILD)
        print(f"[InveNOIR] Synced {len(commands)} commands to guild {GUILD_ID}", flush=True)

    async def on_ready(self):
        print(f"[InveNOIR] READY: {self.user} / {VERSION}", flush=True)


client = SetupClient()
setup_lock = asyncio.Lock()


def authorized(interaction):
    g = interaction.guild
    if g is None or g.id != GUILD_ID:
        return False
    return interaction.user.id == g.owner_id or bool(getattr(interaction.user.guild_permissions, "administrator", False))


def by_name(items, name):
    return next((item for item in items if item.name == name), None)


def staff_overwrites(guild, roles_by_name):
    # Always a DICT. Never pass None for overwrites.
    result = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for role_name in ("Organizer", "Staff", "Judge"):
        role = roles_by_name.get(role_name)
        if role is not None:
            result[role] = discord.PermissionOverwrite(view_channel=True)
    return result


def private_category_safe(category, guild, roles_by_name):
    # If an existing category can be viewed by @everyone or unrelated roles,
    # refuse to create sensitive channels inside it. Never edit existing permissions.
    try:
        if category.overwrites_for(guild.default_role).view_channel is not False:
            return False
        allowed = {guild.default_role.id} | {
            role.id for role in (roles_by_name.get(x) for x in ("Organizer", "Staff", "Judge"))
            if role is not None
        }
        return not any(
            target.id not in allowed and perms.view_channel is True
            for target, perms in category.overwrites.items()
        )
    except (AttributeError, TypeError):
        return False


def plan(guild):
    missing_roles = [name for name, _ in ROLE_CONFIG if by_name(guild.roles, name) is None]
    missing_categories = [name for name, _ in SECTIONS if by_name(guild.categories, name) is None]
    missing_channels = []
    for category_name, channel_specs in SECTIONS:
        category = by_name(guild.categories, category_name)
        for _, channel_name, _ in channel_specs:
            if category is None or by_name(category.channels, channel_name) is None:
                missing_channels.append(channel_name)
    return missing_roles, missing_categories, missing_channels


async def build_server(guild):
    made = {"roles": 0, "categories": 0, "channels": 0}
    errors = []
    role_by_name = {}
    for name, color in ROLE_CONFIG:
        role = by_name(guild.roles, name)
        if role is None:
            try:
                role = await guild.create_role(
                    name=name, colour=discord.Colour(color), reason="InveNOIR setup v4")
                made["roles"] += 1
            except (discord.HTTPException, discord.Forbidden, TypeError, ValueError) as e:
                errors.append(f"ยศ {name}: {e}")
                continue
        role_by_name[name] = role

    for category_name, channels in SECTIONS:
        is_private = category_name == "✧ Staff Only 🔒"
        category = by_name(guild.categories, category_name)
        private_perms = privacy_overwrites_for_new(guild, category_name, None)
        if category is None:
            try:
                category = await guild.create_category(
                    category_name, overwrites=private_perms, reason="InveNOIR secure setup v6")
                made["categories"] += 1
            except (discord.HTTPException, TypeError, ValueError) as e:
                errors.append(f"หมวด {category_name}: {e}")
                continue
        elif is_private and not private_category_safe(category, guild, role_by_name):
            errors.append("หมวด Staff Only ที่มีอยู่ อาจไม่ส่วนตัว: ไม่เพิ่มห้อง กรุณาใช้ /privacy_apply ก่อน")
            continue

        for kind, name, topic in channels:
            if by_name(category.channels, name) is not None:
                continue
            opts = {"category": category, "reason": "InveNOIR setup v4"}
            # New channels are born with the correct privacy policy, even before /privacy_apply.
            opts["overwrites"] = privacy_overwrites_for_new(guild, category_name, name)
            try:
                if kind == "voice":
                    await guild.create_voice_channel(name, **opts)
                elif kind == "forum":
                    await guild.create_forum(name, topic=topic, **opts)
                else:
                    await guild.create_text_channel(name, topic=topic, **opts)
                made["channels"] += 1
            except (discord.HTTPException, TypeError, ValueError) as e:
                errors.append(f"ห้อง {name}: {e}")
                print(f"[InveNOIR] Could not create channel {name}: {e}", flush=True)
    return made, errors


# ------------------------------------------------------------
# Role manager v5 - does not touch anyone's current role assignments.
# ------------------------------------------------------------
SELF_ROLE_NAMES = ("Vocalist", "VTuber", "Mixer", "Artist", "Animator", "Audience")
ROLE_HOIST = frozenset(name for name, _ in ROLE_CONFIG)
ROLE_GROUP_NAMES = tuple(name for name, _ in ROLE_CONFIG)
STAFF_ROLE_NAMES = {"Organizer", "Staff"}
ROLE_DESCRIPTIONS = {
    "Organizer": "ผู้จัดงาน: จัดการห้อง/ข้อความ/อีเวนต์ (ไม่ใช่ Administrator)",
    "Staff": "ทีมงาน: ดูแลข้อความและใช้ Timeout ได้",
    "Judge": "คณะกรรมการ: เข้าถึงห้องตัดสินและส่งผลงาน",
    "Team Leader": "หัวหน้าทีม: ป้ายตำแหน่ง ไม่มีสิทธิ์แอดมิน",
    "Vocalist": "นักร้อง",
    "VTuber": "ผู้เข้าร่วมสาย VTuber",
    "Mixer": "มิกเซอ",
    "Artist": "นักวาด",
    "Animator": "อนิเมเตอร์",
    "Audience": "ผู้ติดตามการแข่งขัน",
}
SENSITIVE_ROLE_FLAGS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_messages",
    "manage_threads", "manage_webhooks", "ban_members", "kick_members", "moderate_members",
    "manage_events", "mention_everyone", "manage_nicknames", "view_audit_log",
)


def desired_permissions(name, current=None):
    # Organizer / Staff keep any deliberate existing rights; add basic moderation only.
    # Everyone else gets NO server-wide powers, so they can never self-assign staff powers.
    if name in STAFF_ROLE_NAMES:
        perms = discord.Permissions(current.value if current is not None else 0)
        if name == "Organizer":
            perms.update(manage_channels=True, manage_messages=True,
                         manage_threads=True, manage_events=True, view_audit_log=True)
        else:
            perms.update(manage_messages=True, manage_threads=True, moderate_members=True)
        return perms
    return discord.Permissions.none()


def bot_can_manage_role(guild, role):
    me = guild.me
    return bool(me and me.guild_permissions.manage_roles and role < me.top_role
                and not role.managed and not role.is_default())


def self_roles_safe(guild):
    # The picker only grants these 6 explicitly allowed names, with no elevated permissions.
    found = {}
    for name in SELF_ROLE_NAMES:
        role = by_name(guild.roles, name)
        if role is None:
            return None, f"ยังไม่มี Role {name}: ให้ใช้ /roles_apply ก่อน"
        if any(getattr(role.permissions, flag, False) for flag in SENSITIVE_ROLE_FLAGS):
            return None, f"Role {name} มีสิทธิ์สูงเกินไป ใช้ /roles_apply เพื่อปรับสิทธิ์ก่อน"
        if not bot_can_manage_role(guild, role):
            return None, f"บอทจัดการ Role {name} ไม่ได้: ย้ายยศของบอทให้สูงกว่ายศสมาชิกใน Server Settings → Roles"
        found[name] = role
    return found, None


class SelfRoleSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Vocalist", emoji="🎤", description="นักร้อง"),
            discord.SelectOption(label="VTuber", emoji="🎭", description="VTuber"),
            discord.SelectOption(label="Mixer", emoji="🎧", description="มิกเซอ"),
            discord.SelectOption(label="Artist", emoji="🎨", description="นักวาด"),
            discord.SelectOption(label="Animator", emoji="🎬", description="ตัดต่อวิดิโอ"),
            discord.SelectOption(label="Audience", emoji="💜", description="ผู้ติดตามการแข่งขัน"),
        ]
        super().__init__(placeholder="เลือกบทบาทของคุณ (เลือกได้หลายอย่าง)",
                         min_values=1, max_values=len(options), options=options,
                         custom_id="invenoir:v5:self_role_select")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID:
            return await interaction.response.send_message("ใช้ได้เฉพาะเซิร์ฟเวอร์ InveNOIR", ephemeral=True)
        roles, problem = self_roles_safe(interaction.guild)
        if problem:
            return await interaction.response.send_message("❌ " + problem, ephemeral=True)
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("ไม่พบข้อมูลสมาชิก กรุณาลองใหม่", ephemeral=True)
        member = interaction.user
        chosen = set(self.values)
        to_add = [role for name, role in roles.items() if name in chosen and role not in member.roles]
        to_remove = [role for name, role in roles.items() if name not in chosen and role in member.roles]
        await interaction.response.defer(ephemeral=True)
        try:
            if to_remove:
                await member.remove_roles(*to_remove, reason="InveNOIR self roles v5")
            if to_add:
                await member.add_roles(*to_add, reason="InveNOIR self roles v5")
            selected = ", ".join(name for name in SELF_ROLE_NAMES if name in chosen)
            await interaction.followup.send("✅ อัปเดตบทบาทสำเร็จ: " + selected, ephemeral=True)
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"❌ ไม่สามารถอัปเดตบทบาทได้: {str(exc)[:280]}\nตรวจสิทธิ์ Manage Roles และตำแหน่งยศบอท",
                ephemeral=True,
            )


class SelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SelfRoleSelect())


async def apply_role_settings(guild):
    results = {"created": 0, "updated": 0, "same": 0, "access": 0, "order": 0}
    errors = []
    for name, color in ROLE_CONFIG:
        current = by_name(guild.roles, name)
        try:
            permissions = desired_permissions(name, current.permissions if current else None)
            kwargs = {"colour": discord.Colour(color), "hoist": name in ROLE_HOIST,
                      "mentionable": False, "permissions": permissions,
                      "reason": "InveNOIR roles configuration v5"}
            if current is None:
                await guild.create_role(name=name, **kwargs)
                results["created"] += 1
            elif not bot_can_manage_role(guild, current):
                errors.append(f"{name}: บอทไม่มียศสูงพอ หรือ Role ถูกจัดการโดยแอปอื่น")
            elif (current.colour.value == color and current.hoist == kwargs["hoist"]
                  and current.mentionable is False and current.permissions.value == permissions.value):
                results["same"] += 1
            else:
                await current.edit(**kwargs)
                results["updated"] += 1
        except (discord.HTTPException, TypeError, ValueError) as exc:
            errors.append(f"{name}: {str(exc)[:160]}")

    # Put the 10 roles in the desired seniority order, using only their existing slots.
    # Thus unrelated / bot roles keep their slot. Skip if even one managed role is out of reach.
    ordered_roles = [by_name(guild.roles, n) for n, _ in ROLE_CONFIG]
    if all(r is not None and bot_can_manage_role(guild, r) for r in ordered_roles):
        slots = sorted((r.position for r in ordered_roles), reverse=True)
        positions = {r: slot for r, slot in zip(ordered_roles, slots) if r.position != slot}
        if positions:
            try:
                await guild.edit_role_positions(positions=positions, reason="InveNOIR role order v5")
                results["order"] = len(positions)
            except (discord.HTTPException, TypeError, ValueError) as exc:
                errors.append("เรียงยศ: " + str(exc)[:140])
    else:
        errors.append("เรียงยศ: ข้าม เพราะยศบางอันสูงกว่ายศบอทหรือไม่สามารถแก้ได้")

    # Apply minimum-scoped channel permissions only to known InveNOIR channels.
    # Do not replace existing overwrite dictionaries or expose private staff areas.
    for name in READ_ONLY_CHANNELS:
        target = discord.utils.get(guild.text_channels, name=name)
        if target is None:
            continue
        for role_name in ("Organizer", "Staff"):
            role = by_name(guild.roles, role_name)
            if role is None:
                continue
            try:
                existing = target.overwrites_for(role)
                if existing.send_messages is not True:
                    await target.set_permissions(role, overwrite=update_overwrite(existing, send_messages=True),
                                                 reason="InveNOIR role access v5")
                    results["access"] += 1
            except discord.HTTPException as exc:
                errors.append(f"การประกาศ {name}/{role_name}: {str(exc)[:120]}")

    # Judges may see two specific rooms, not the entire staff working area.
    judge = by_name(guild.roles, "Judge")
    staff_category = by_name(guild.categories, "✧ Staff Only 🔒")
    if judge and staff_category:
        judging_rooms = {"⚖️・judging-room", "🗃️・submissions"}
        for room in staff_category.text_channels:
            allowed = room.name in judging_rooms
            try:
                existing = room.overwrites_for(judge)
                if existing.view_channel is not allowed:
                    await room.set_permissions(
                        judge, overwrite=update_overwrite(existing, view_channel=allowed),
                        reason="InveNOIR judge room privacy v5")
                    results["access"] += 1
            except discord.HTTPException as exc:
                errors.append(f"Judge room {room.name}: {str(exc)[:120]}")
    return results, errors


def update_overwrite(overwrite, **settings):
    # Keep the channel's other permission fields intact.
    new = discord.PermissionOverwrite.from_pair(*overwrite.pair())
    new.update(**settings)
    return new


@client.tree.command(name="roles_preview", description="ดูแผนสีและสิทธิ์ยศ InveNOIR ก่อนแก้จริง", guild=TARGET_GUILD)
async def roles_preview(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์/Administrator", ephemeral=True)
    missing = [n for n, _ in ROLE_CONFIG if by_name(interaction.guild.roles, n) is None]
    unsafe = [n for n in SELF_ROLE_NAMES if (r := by_name(interaction.guild.roles, n)) and
              any(getattr(r.permissions, x, False) for x in SENSITIVE_ROLE_FLAGS)]
    text = (f"🎨 InveNOIR {VERSION} — ตั้งค่ายศ 10 ยศ\n"
            "Organizer: จัดการห้อง/ประกาศ | Staff: ดูแลแชท/Timeout\n"
            "Judge: ห้องตัดสิน | Team Leader: ป้ายหัวหน้าทีม\n"
            "Vocalist / VTuber / Mixer / Aritst / Animator / Audience: ไม่มีสิทธิ์แอดมิน\n"
            "ทุกยศ: สีตามธีม, ไม่เปิดให้ @mention ยศ; ทุกยศแสดงแยกในรายชื่อสมาชิก\n"
            f"ยศที่ขาด: {', '.join(missing) if missing else 'ไม่มี'}\n"
            f"ยศสมาชิกที่มีสิทธิ์สูงและจะถูกปรับ: {', '.join(unsafe) if unsafe else 'ไม่มี'}\n"
            "ไม่ลบ/เปลี่ยนยศที่ติดอยู่กับสมาชิก ไม่แตะห้องนอก InveNOIR\n"
            "สั่ง `/roles_apply confirm:true` เพื่อยืนยัน")
    await interaction.response.send_message(text, ephemeral=True)


@client.tree.command(name="roles_apply", description="ตั้งค่าสี/สิทธิ์ยศ InveNOIR (ยืนยันก่อน)", guild=TARGET_GUILD)
@app_commands.describe(confirm="true เพื่อแก้ไขยศจริง")
async def roles_apply(interaction: discord.Interaction, confirm: bool):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์/Administrator", ephemeral=True)
    if not confirm:
        return await interaction.response.send_message("ยังไม่เปลี่ยนอะไร ให้เลือก confirm:true", ephemeral=True)
    if setup_lock.locked():
        return await interaction.response.send_message("มีงานจัดเซิร์ฟเวอร์ทำอยู่ กรุณาลองอีกครั้งหลังคำสั่งเดิมจบ", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with setup_lock:
        try:
            done, errors = await apply_role_settings(interaction.guild)
            result = (f"✅ InveNOIR Roles {VERSION}\n"
                      f"สร้างยศ {done['created']} | ปรับยศ {done['updated']} | ตั้งค่าแล้ว {done['same']}\n"
                      f"เรียงลำดับยศ {done['order']} ยศ | ปรับสิทธิ์ห้อง {done['access']} จุด\n"
                      "ต่อไปใช้ `/roles_panel` เพื่อเปิดเมนูเลือกยศให้สมาชิก")
            if errors:
                result += "\n⚠️ บางรายการไม่สำเร็จ:\n" + "\n".join(errors[:7])
                if len(errors) > 7:
                    result += f"\nและอีก {len(errors) - 7} รายการ"
            await interaction.followup.send(result[:1900], ephemeral=True)
        except Exception as exc:
            traceback.print_exc()
            await interaction.followup.send(f"❌ roles_apply: {type(exc).__name__}: {str(exc)[:300]}", ephemeral=True)


# ------------------------------------------------------------
# Role groups v8 - show each InveNOIR role as a separate heading
# in Discord's right-side member list. This only changes role.hoist.
# It does NOT edit permissions, colours, role positions, assignments,
# channel access, panel messages, or any non-InveNOIR roles.
# ------------------------------------------------------------
def role_groups_plan(guild):
    results = {"ready": [], "to_enable": [], "missing": [], "blocked": []}
    for name in ROLE_GROUP_NAMES:
        role = by_name(guild.roles, name)
        if role is None:
            results["missing"].append(name)
        elif role.hoist:
            results["ready"].append(name)
        elif not bot_can_manage_role(guild, role):
            results["blocked"].append(name)
        else:
            results["to_enable"].append(name)
    return results


async def enable_role_groups(guild):
    # Re-check each role immediately before changing, for safety.
    done, already, missing, blocked, errors = [], [], [], [], []
    for name in ROLE_GROUP_NAMES:
        role = by_name(guild.roles, name)
        if role is None:
            missing.append(name)
            continue
        if role.hoist:
            already.append(name)
            continue
        if not bot_can_manage_role(guild, role):
            blocked.append(name)
            continue
        try:
            await role.edit(hoist=True, reason="InveNOIR v8: show role separately in member list")
            done.append(name)
        except (discord.HTTPException, TypeError, ValueError) as exc:
            errors.append(f"{name}: {str(exc)[:150]}")
    return {"enabled": done, "already": already, "missing": missing,
            "blocked": blocked, "errors": errors}


@client.tree.command(name="role_groups_preview", description="ดูยศที่จะเปิดแสดงแยกในรายชื่อสมาชิก", guild=TARGET_GUILD)
async def role_groups_preview(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์/Administrator", ephemeral=True)
    plan = role_groups_plan(interaction.guild)
    out = (
        f"👥 InveNOIR {VERSION} — แยกสมาชิกตามยศ 10 ยศ\n"
        f"✅ แสดงแยกแล้ว ({len(plan['ready'])}): {', '.join(plan['ready']) or '-'}\n"
        f"🛠️ จะเปิดเพิ่ม ({len(plan['to_enable'])}): {', '.join(plan['to_enable']) or '-'}\n"
        f"⚠️ บอทแก้ไม่ได้ ({len(plan['blocked'])}): {', '.join(plan['blocked']) or '-'}\n"
        f"❓ ยศไม่พบ ({len(plan['missing'])}): {', '.join(plan['missing']) or '-'}\n"
        "ไม่เปลี่ยนสิทธิ์ห้อง/สมาชิก ไม่ย้ายหรือลบยศ และไม่แตะ Role อื่น\n"
        "Discord แสดงสมาชิกภายใต้ยศที่แสดงแยกซึ่งอยู่สูงสุดเพียงยศเดียว\n"
        "ใช้ `/role_groups_apply confirm:true` เพื่อเปิดจริง"
    )
    await interaction.response.send_message(out[:1900], ephemeral=True)


@client.tree.command(name="role_groups_apply", description="เปิดแสดงสมาชิกแยกตามทุกยศ InveNOIR", guild=TARGET_GUILD)
@app_commands.describe(confirm="เลือก true เพื่อให้บอทเปิดแสดงยศจริง")
async def role_groups_apply(interaction: discord.Interaction, confirm: bool):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์/Administrator", ephemeral=True)
    if not confirm:
        return await interaction.response.send_message("ยังไม่เปลี่ยนอะไร เลือก confirm:true ก่อน", ephemeral=True)
    if setup_lock.locked():
        return await interaction.response.send_message("บอทกำลังจัดเซิร์ฟเวอร์อยู่ กรุณาลองใหม่", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with setup_lock:
        try:
            result = await enable_role_groups(interaction.guild)
            out = (f"👥 InveNOIR {VERSION} — แสดงยศแยกเรียบร้อย\n"
                   f"✅ เปิดเพิ่ม: {len(result['enabled'])} ยศ\n"
                   f"✅ เปิดอยู่แล้ว: {len(result['already'])} ยศ\n"
                   f"❓ ยศขาด: {', '.join(result['missing']) or '-'}\n"
                   f"⚠️ บอทไม่มีสิทธิ์แก้: {', '.join(result['blocked']) or '-'}\n"
                   "ไม่แก้สิทธิ์/ลำดับ/สีของยศ หรือสิทธิ์ห้องใด ๆ\n"
                   "ถ้าเห็นสมาชิกอยู่ผิดกลุ่ม ให้ตรวจลำดับยศที่ Server Settings → Roles")
            if result['errors']:
                out += "\n❌ ปรับไม่สำเร็จ:\n" + "\n".join(result['errors'][:5])
            await interaction.followup.send(out[:1900], ephemeral=True)
        except Exception as exc:
            traceback.print_exc()
            await interaction.followup.send(
                f"❌ role_groups_apply: {type(exc).__name__}: {str(exc)[:300]}", ephemeral=True)


ROLE_PANEL_MARKER = "INVENOIR_ONBOARDING_ROLE_PICKER_V7"


def role_panel_embed():
    embed = discord.Embed(
        title="🎭 InveNOIR | รับยศเพื่อปลดล็อกเซิร์ฟเวอร์",
        description=(
            "**ยินดีต้อนรับ!** เลือกยศอย่างน้อย 1 อย่างด้านล่าง แล้วคุณจะเห็นห้องแนะนำตัว "
            "ห้องหาทีม และห้องแชทของสมาชิกทันที\n\n"
            "🎤 Vocalist · 🎭 VTuber · 🎧 Mixer · 🎨 Artist · 🎬 Animator · 💜 Audience\n\n"
            "เลือกได้หลายตำแหน่ง กรณีต้องการเปลี่ยนยศให้เลือก **ทุกยศที่ต้องการเก็บไว้** อีกครั้ง\n"
            "ตำแหน่ง Organizer, Staff, Judge, Team Leader มอบให้โดยทีมงานเท่านั้น"
        ),
        colour=discord.Colour(0xB583EB),
    )
    embed.set_footer(text=ROLE_PANEL_MARKER)
    return embed


async def ensure_role_panel(channel):
    """Edit a matching old v7 panel instead of posting duplicates."""
    msg = None
    try:
        async for old in channel.history(limit=60):
            if old.author.id == client.user.id and any(
                emb.footer and emb.footer.text == ROLE_PANEL_MARKER for emb in old.embeds
            ):
                msg = old
                break
    except (discord.Forbidden, discord.HTTPException):
        pass
    if msg is not None:
        await msg.edit(embed=role_panel_embed(), view=SelfRoleView())
        return "อัปเดตเมนูยศใน"
    await channel.send(embed=role_panel_embed(), view=SelfRoleView())
    return "สร้างเมนูยศใน"




# ------------------------------------------------------------
# v9.1 -- In-place role rename (keep ID/member assignments/overwrites).
# Deliberately no automatic rename on startup; owner must opt in.
# ------------------------------------------------------------
def audience_migration_state(guild):
    old = by_name(guild.roles, "Supporter")
    new = by_name(guild.roles, "Audience")
    if old and new:
        return "conflict", old, new
    if old:
        return "rename", old, None
    if new:
        return "ready", None, new
    return "missing", None, None


@client.tree.command(name="audience_preview", description="ดูแผนเปลี่ยน Supporter เป็น Audience โดยเก็บสมาชิกเดิม", guild=TARGET_GUILD)
async def audience_preview(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์/Administrator", ephemeral=True)
    state, old, new = audience_migration_state(interaction.guild)
    responses = {
        "rename": "พบยศ Supporter เดิม จะเปลี่ยนชื่อเป็น Audience (ID เดิม) สมาชิก/สิทธิ์เดิมยังอยู่",
        "ready": "มี Audience อยู่แล้ว ไม่ต้องสร้างซ้ำ จะอัปเดตเมนูเลือกยศเท่านั้น",
        "conflict": "พบทั้ง Supporter และ Audience — จะไม่แก้ไขโดยอัตโนมัติ เพื่อไม่ให้เกิดยศซ้ำ",
        "missing": "ไม่พบทั้ง Supporter และ Audience — ใช้ /roles_apply เพื่อสร้าง Audience ก่อน",
    }
    suffix = "\nใช้ /audience_apply confirm:true เพื่อดำเนินการ" if state in {"rename", "ready"} else "\nยังไม่สามารถดำเนินการได้"
    await interaction.response.send_message("🎭 InveNOIR Audience — PREVIEW\n" + responses[state] + suffix, ephemeral=True)


@client.tree.command(name="audience_apply", description="เปลี่ยน Supporter เป็น Audience และอัปเดตเมนูเลือกยศ", guild=TARGET_GUILD)
@app_commands.describe(confirm="true เพื่อยืนยันการเปลี่ยนชื่อยศและอัปเดตเมนู")
async def audience_apply(interaction: discord.Interaction, confirm: bool):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์/Administrator", ephemeral=True)
    if not confirm:
        return await interaction.response.send_message("ยังไม่เปลี่ยนแปลงอะไร ให้เลือก confirm:true", ephemeral=True)
    if setup_lock.locked():
        return await interaction.response.send_message("มีงานจัดเซิร์ฟเวอร์อื่นกำลังทำงานอยู่", ephemeral=True)
    state, old, new = audience_migration_state(interaction.guild)
    if state == "conflict":
        return await interaction.response.send_message(
            "❌ มีทั้ง Supporter และ Audience อยู่แล้ว จึงไม่เปลี่ยนชื่อหรือรวมยศอัตโนมัติ กรุณาตรวจใน Server Settings → Roles", ephemeral=True)
    if state == "missing":
        return await interaction.response.send_message(
            "❌ ไม่พบ Supporter หรือ Audience กรุณาใช้ /roles_apply confirm:true เพื่อสร้าง Audience ก่อน", ephemeral=True)
    if state == "rename" and not bot_can_manage_role(interaction.guild, old):
        return await interaction.response.send_message(
            "❌ บอทต้องมี Manage Roles และยศบอทต้องอยู่สูงกว่า Supporter", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with setup_lock:
        outcome = ""
        try:
            # Recheck after acquiring lock to avoid racing with another command.
            state, old, new = audience_migration_state(interaction.guild)
            if state == "rename":
                if not bot_can_manage_role(interaction.guild, old):
                    return await interaction.followup.send("❌ บอทแก้ยศ Supporter ไม่ได้", ephemeral=True)
                renamed = await old.edit(name="Audience", reason="InveNOIR v9.1 Supporter -> Audience")
                outcome = f"✅ เปลี่ยนชื่อ Supporter → Audience (Role ID {renamed.id} เดิม)\n"
            elif state == "ready":
                outcome = "✅ ยศ Audience มีอยู่แล้ว ไม่สร้างเพิ่ม\n"
            else:
                return await interaction.followup.send("❌ พบยศขัดแย้งหรือหายไป กรุณาตรวจ /audience_preview อีกครั้ง", ephemeral=True)
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError) as exc:
            return await interaction.followup.send(f"❌ เปลี่ยนยศไม่สำเร็จ: {str(exc)[:290]}", ephemeral=True)
        channel = choose_channel(interaction.guild)
        if channel is None:
            outcome += "⚠️ ไม่พบห้อง choose-your-role กรุณาสร้างห้องก่อนแล้วสั่ง /roles_panel"
        else:
            try:
                action = await ensure_role_panel(channel)
                outcome += f"✅ {action} {channel.mention} เป็น Audience แล้ว\n"
            except (discord.Forbidden, discord.HTTPException) as exc:
                outcome += f"⚠️ เปลี่ยนชื่อยศแล้ว แต่แก้เมนูไม่สำเร็จ: {str(exc)[:180]}\nลอง /roles_panel อีกครั้ง"
        outcome += "\nไม่ลบยศ ไม่ถอดยศสมาชิก และไม่เปลี่ยนสิทธิ์ห้อง"
        await interaction.followup.send(outcome[:1900], ephemeral=True)

@client.tree.command(name="roles_panel", description="สร้างหรืออัปเดตเมนูรับยศในห้อง choose-your-role", guild=TARGET_GUILD)
async def roles_panel(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์/Administrator", ephemeral=True)
    _, problem = self_roles_safe(interaction.guild)
    if problem:
        return await interaction.response.send_message("❌ " + problem, ephemeral=True)
    channel = choose_channel(interaction.guild)
    if channel is None:
        return await interaction.response.send_message(
            "❌ ไม่พบห้อง choose-your-role กรุณาใช้ /onboarding_apply confirm:true ก่อน", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        action = await ensure_role_panel(channel)
        await interaction.followup.send(f"✅ {action} {channel.mention} แล้ว • คนยังไม่มียศกดเลือกได้", ephemeral=True)
    except discord.HTTPException as exc:
        await interaction.followup.send(f"❌ ตั้งเมนูไม่ได้: {str(exc)[:300]}", ephemeral=True)




# ------------------------------------------------------------
# Privacy Manager v6 — categories AND children, including unsynced channels.
# No member-role assignments or messages are changed.
# ------------------------------------------------------------
PRIVACY_BACKUP_FILE = DATA_DIR / "privacy_backup_original.json"
MODERATORS = frozenset({"Organizer", "Staff"})
COMPETITORS = frozenset({"Vocalist", "VTuber", "Mixer", "Artist", "Animator", "Team Leader"})
REGISTERED = COMPETITORS | {"Audience"}
READERS = REGISTERED | {"Judge"}
ROLE_NAME_SET = frozenset(n for n, _ in ROLE_CONFIG)


def privacy_category_type(name):
    label = unicodedata.normalize("NFKC", name).casefold()
    # Typical category variants seen in this server: Welcome, ✧ Welcome, 𝒲welcome
    compact = re.sub(r"[^a-z]", "", label)
    if compact in {"welcome", "wwelcome", "fwelcome"}:
        return "welcome"
    common = {"chorusbattle": "battle", "teamfinder": "finder",
              "community": "community", "voicechannels": "voice",
              "staffonly": "staff", "teamrooms": "teamrooms", "registeredteams": "registeredteams"}
    if compact in common:
        return common[compact]
    return "other"


def room_key(name):
    """Identify room by its suffix regardless of emoji/Unicode bullet used."""
    if not name:
        return ""
    value = unicodedata.normalize("NFKC", name).casefold()
    value = re.sub(r"^[^a-z0-9ก-๙]+", "", value)
    if "・" in value:
        value = value.rsplit("・", 1)[-1]
    elif "•" in value:
        value = value.rsplit("•", 1)[-1]
    return value.strip(" -·•_.")


def is_group_finder(name):
    return room_key(name) == "group-finder"


def is_team_chat(name):
    return room_key(name) == "team-chat"


def is_member_profiles(name):
    return room_key(name) == "member-profiles"


def choose_channel(guild):
    return next((c for c in guild.text_channels
                 if c.category and privacy_category_type(c.category.name) == "welcome"
                 and room_key(c.name) == "choose-your-role"), None)


def welcome_category(guild):
    return next((c for c in guild.categories if privacy_category_type(c.name) == "welcome"), None)


def finder_category(guild):
    return next((c for c in guild.categories if privacy_category_type(c.name) == "finder"), None)


def privacy_policy(category_name, room_name=None):
    typ = privacy_category_type(category_name)
    key = room_key(room_name)
    if typ == "welcome":
        if room_name is None:
            return True, set(ROLE_NAME_SET), "หมวดต้อนรับของทุกคน"
        if key in {"welcome", "announcements", "rules", "information", "choose-your-role", "info"}:
            return True, set(ROLE_NAME_SET), "ทุกคน รวมถึงคนที่ยังไม่มียศ"
        # Introduce-yourself is available AFTER receiving a self-role.
        return False, set(READERS | MODERATORS), "ห้องแนะนำตัวหลังรับยศ"
    if typ in {"battle", "community"}:
        return False, set(READERS | MODERATORS), "สมาชิกที่มียศและกรรมการ"
    if typ == "finder":
        if room_name is None:
            return False, set(READERS | MODERATORS), "หมวดหาทีมสำหรับผู้มียศ"
        if is_group_finder(room_name) or is_team_chat(room_name):
            return False, set(READERS | MODERATORS), "หาทีม/แชทรวมสำหรับทุกยศ"
        if is_member_profiles(room_name):
            return False, set(COMPETITORS | MODERATORS), "โปรไฟล์สมาชิกสำหรับสายงานที่เกี่ยวข้องกับการแข่งขัน"
        # Keep legacy rooms staff-only until owner confirms deletion.
        return False, set(MODERATORS), "ห้องเก่าที่เตรียมลบ (ทีมงานเท่านั้น)"
    if typ == "voice":
        allowed = set(READERS | MODERATORS)
        if room_name and "Team Meeting" in room_name:
            allowed = set(COMPETITORS | MODERATORS)
        return False, allowed, "ห้องเสียงสมาชิก/ประชุมทีม"
    if typ == "staff":
        allowed = set(MODERATORS)
        if room_name and ("・judging-room" in room_name or "・submissions" in room_name):
            allowed.add("Judge")
        return False, allowed, "ห้องเจ้าหน้าที่/กรรมการ"
    if typ == "teamrooms":
        # Group Finder private team rooms have individual member overwrites.
        return False, set(MODERATORS), "ห้องคุยส่วนตัวของ Group Finder"
    if typ == "registeredteams":
        # Competition registration rooms have individual roster overwrites.
        return False, set(MODERATORS), "ห้องทีมที่สมัครแข่งขันแล้ว"
    return False, set(MODERATORS), "หมวดอื่น: ทีมงานเท่านั้น"


def privacy_readonly(room_name):
    if not room_name:
        return False
    return room_key(room_name) in {
        "welcome", "announcements", "rules", "information", "choose-your-role", "member-profiles",
        "themes", "schedule", "registration", "results", "info", "ข่าวสาร", "ประกาศ", "กติกา"
    }


def is_member_writable(category_name, room_name):
    """Explicitly allow roleholders to speak where @everyone may be locked."""
    if not room_name or privacy_readonly(room_name):
        return False
    typ = privacy_category_type(category_name)
    if typ == "welcome":
        return room_key(room_name) == "introduce-yourself"
    if typ == "finder":
        return is_group_finder(room_name) or is_team_chat(room_name)
    return typ in {"battle", "community", "staff"}




def privacy_overwrites_for_new(guild, category_name, room_name=None):
    is_public, allowed, _ = privacy_policy(category_name, room_name)
    everyone = discord.PermissionOverwrite(view_channel=is_public)
    # Newcomers read the welcome instructions and CLICK the component;
    # they cannot post messages until they have a role.
    if privacy_readonly(room_name):
        everyone.update(send_messages=False, send_messages_in_threads=False,
                        create_public_threads=False, create_private_threads=False,
                        read_message_history=True)
    result = {guild.default_role: everyone}
    for name in allowed:
        role = by_name(guild.roles, name)
        if role is None:
            continue
        r = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
        if privacy_readonly(room_name) and name in MODERATORS:
            r.update(send_messages=True, send_messages_in_threads=True)
        elif is_member_writable(category_name, room_name):
            r.update(send_messages=True, send_messages_in_threads=True,
                     create_public_threads=True, add_reactions=True)
        result[role] = r
    return result


def privacy_desired_overwrites(guild, channel):
    cat_name = channel.name if isinstance(channel, discord.CategoryChannel) else (
        channel.category.name if channel.category else "<uncategorized>")
    room_name = None if isinstance(channel, discord.CategoryChannel) else channel.name
    is_public, allowed, _ = privacy_policy(cat_name, room_name)
    result = {target: discord.PermissionOverwrite.from_pair(*ov.pair())
              for target, ov in channel.overwrites.items()}
    everyone = result.setdefault(guild.default_role, discord.PermissionOverwrite())
    everyone.view_channel = is_public
    if privacy_readonly(room_name):
        everyone.update(send_messages=False, send_messages_in_threads=False,
                        create_public_threads=False, create_private_threads=False,
                        read_message_history=True)
    # Clean explicit view grants of any unmanaged role/member, but preserve other flags.
    tracked_ids = {guild.default_role.id}
    # Preserve the bot's own explicit overwrite in sensitive staff-only channels.
    if guild.me is not None:
        tracked_ids.add(guild.me.id)
    for name, _ in ROLE_CONFIG:
        role = by_name(guild.roles, name)
        if role is None:
            continue
        tracked_ids.add(role.id)
        ov = result.setdefault(role, discord.PermissionOverwrite())
        ov.view_channel = True if name in allowed else None
        if name in allowed:
            ov.read_message_history = True
            if privacy_readonly(room_name):
                if name in MODERATORS:
                    ov.send_messages = True
                    ov.send_messages_in_threads = True
                else:
                    ov.send_messages = False
                    ov.send_messages_in_threads = False
                    ov.create_public_threads = False
                    ov.create_private_threads = False
            elif is_member_writable(cat_name, room_name):
                ov.send_messages = True
                ov.send_messages_in_threads = True
                ov.create_public_threads = True
                ov.add_reactions = True
        else:
            # Never grant writing on channels where this role should not be present.
            ov.send_messages = None
            ov.send_messages_in_threads = None
            ov.create_public_threads = None
    for target, ov in list(result.items()):
        if target.id not in tracked_ids:
            ov.view_channel = None
    return {target: ov for target, ov in result.items() if not ov.is_empty()}




def privacy_overwrites_signature(mapping):
    return {int(t.id): (int(p.pair()[0].value), int(p.pair()[1].value))
            for t, p in mapping.items() if not p.is_empty()}


def privacy_all_channels(guild):
    # Dynamic per-team rooms have member-specific overwrites. Never normalize them with the
    # global role policy, or a later /privacy_apply could accidentally remove roster access.
    private_team_category_ids = {
        c.id for c in guild.categories
        if privacy_category_type(c.name) in {"teamrooms", "registeredteams"}
    }
    protected_review_ids = {
        ch.id for ch in guild.text_channels
        if room_key(ch.name) in {"team-registration-review", "full-team-applications"}
    }
    targets = []
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel) and ch.id in private_team_category_ids:
            continue
        if getattr(ch, "category_id", None) in private_team_category_ids:
            continue
        if ch.id in protected_review_ids:
            continue
        targets.append(ch)
    return sorted(targets, key=lambda ch: (0 if isinstance(ch, discord.CategoryChannel) else 1,
                                           getattr(ch, "position", 0), ch.id))


def privacy_preview_data(guild):
    targets = privacy_all_channels(guild)
    changes = [ch for ch in targets if privacy_overwrites_signature(ch.overwrites)
               != privacy_overwrites_signature(privacy_desired_overwrites(guild, ch))]
    public_ch = [ch for ch in targets if not isinstance(ch, discord.CategoryChannel)
                 and privacy_category_type(ch.category.name if ch.category else "") == "welcome"]
    unfamiliar = [ch.name for ch in targets if isinstance(ch, discord.CategoryChannel)
                  and privacy_category_type(ch.name) == "other"]
    lonely = [ch.name for ch in targets if not isinstance(ch, discord.CategoryChannel)
              and ch.category is None]
    return targets, changes, public_ch, unfamiliar, lonely


def privacy_snapshot(guild):
    snapshot = {"guild_id": guild.id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "version": VERSION, "channels": []}
    for ch in privacy_all_channels(guild):
        overrides = []
        for t, p in ch.overwrites.items():
            allow, deny = p.pair()
            overrides.append({"id": t.id,
                              "type": "role" if isinstance(t, discord.Role) else "member",
                              "allow": allow.value, "deny": deny.value})
        snapshot["channels"].append({"id": ch.id, "name": ch.name, "overwrites": overrides})
    # Save an additional stamped backup each apply, plus latest pointer.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    stamped = DATA_DIR / f"privacy_backup_{guild.id}_{stamp}.json"
    stamped.write_text(text, encoding="utf-8")
    # Preserve the pre-v6 original even if /privacy_apply is run again later.
    if not PRIVACY_BACKUP_FILE.is_file():
        PRIVACY_BACKUP_FILE.write_text(text, encoding="utf-8")
    return stamped.name


async def privacy_apply_all(guild):
    edited = 0
    errors = []
    for ch in privacy_all_channels(guild):
        new = privacy_desired_overwrites(guild, ch)
        if privacy_overwrites_signature(ch.overwrites) == privacy_overwrites_signature(new):
            continue
        try:
            await ch.edit(overwrites=new, reason="InveNOIR privacy v6 / owner confirmed")
            edited += 1
        except (discord.HTTPException, TypeError, ValueError) as exc:
            errors.append(f"{ch.name}: {type(exc).__name__}: {str(exc)[:110]}")
    return edited, errors


async def privacy_restore_all(guild):
    if not PRIVACY_BACKUP_FILE.is_file():
        return 0, ["ไม่พบไฟล์ privacy_backup_original.json ในโฟลเดอร์บอท"]
    data = json.loads(PRIVACY_BACKUP_FILE.read_text(encoding="utf-8"))
    if data.get("guild_id") != guild.id:
        return 0, ["Backup นี้เป็นของเซิร์ฟเวอร์อื่น จึงปฏิเสธการคืนค่า"]
    edited = 0
    problems = []
    for record in data["channels"]:
        ch = guild.get_channel(int(record["id"]))
        if ch is None:
            problems.append(f"Channel ID {record['id']} ไม่อยู่แล้ว")
            continue
        overrides = {}
        for item in record["overwrites"]:
            if item["type"] == "role":
                target = guild.get_role(int(item["id"]))
            else:
                target = guild.get_member(int(item["id"]))
                if target is None:
                    try:
                        target = await guild.fetch_member(int(item["id"]))
                    except discord.HTTPException:
                        target = None
            if target is None:
                problems.append(f"{ch.name}: ไม่พบ Role/Member {item['id']}")
                continue
            overrides[target] = discord.PermissionOverwrite.from_pair(
                discord.Permissions(int(item["allow"])), discord.Permissions(int(item["deny"])))
        try:
            await ch.edit(overwrites=overrides, reason="InveNOIR privacy v6 restore original overwrites")
            edited += 1
        except (discord.HTTPException, TypeError, ValueError) as exc:
            problems.append(f"{ch.name}: {str(exc)[:120]}")
    return edited, problems


@client.tree.command(name="privacy_preview", description="ดูว่าห้องใครเห็นได้บ้างก่อนล็อกสิทธิ์", guild=TARGET_GUILD)
async def privacy_preview(interaction: discord.Interaction):
    if not interaction.guild or interaction.user.id != interaction.guild.owner_id or interaction.guild.id != GUILD_ID:
        return await interaction.response.send_message("คำสั่งนี้สำหรับเจ้าของเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
    targets, changes, public_ch, unfamiliar, lonely = privacy_preview_data(interaction.guild)
    msg = ("🔐 InveNOIR Privacy v6 (ยังไม่ได้แก้จริง)\n"
           f"จะตรวจ {len(targets)} หมวด/ห้อง | ต้องแก้ {len(changes)} จุด\n"
           f"Welcome: คนไม่มียศเห็นได้ {len(public_ch)} ห้อง\n"
           "Chorus Battle / Community: สมาชิกที่มียศ + Judge\n"
           "Team Finder: group-finder + member-profiles + team-chat สำหรับสมาชิก (ห้องเก่าทีมงานเท่านั้น)\n"
           "Voice: สมาชิกที่มียศ; Team Meeting เฉพาะผู้เข้าแข่งขัน\n"
           "Staff: Organizer + Staff; Judge เฉพาะ judging-room / submissions\n"
           "หมวดอื่น/ห้องไม่มีหมวด: Staff เท่านั้น\n"
           f"หมวดอื่นที่จะล็อก: {', '.join(unfamiliar[:4]) or 'ไม่มี'}\n"
           f"ห้องไม่มีหมวดที่จะล็อก: {', '.join(lonely[:4]) or 'ไม่มี'}\n"
           "⚠️ สิทธิ์ Administrator มองเห็นห้องได้เสมอ; ยศซ้อนกันเห็นตามสิทธิ์รวม\n"
           "📌 ใช้ /onboarding_apply confirm:true เพื่อสร้างห้องรับยศและปลดล็อกให้ถูกต้อง")
    await interaction.response.send_message(msg[:1950], ephemeral=True)


@client.tree.command(name="privacy_apply", description="ปรับสิทธิ์ห้องทั้งหมดพร้อมสร้างไฟล์สำรอง", guild=TARGET_GUILD)
@app_commands.describe(confirm="true เพื่ออนุญาตให้แก้สิทธิ์จริง")
async def privacy_apply(interaction: discord.Interaction, confirm: bool):
    if not interaction.guild or interaction.guild.id != GUILD_ID or interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("คำสั่งนี้สำหรับเจ้าของเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
    if not confirm:
        return await interaction.response.send_message("ยังไม่เปลี่ยนอะไร กรุณาเลือก confirm:true", ephemeral=True)
    missing = [name for name, _ in ROLE_CONFIG if by_name(interaction.guild.roles, name) is None]
    if missing:
        return await interaction.response.send_message(
            "❌ ยังมียศที่ขาด: " + ", ".join(missing) + "\nใช้ /roles_apply ก่อน", ephemeral=True)
    me = interaction.guild.me
    if me is None or not me.guild_permissions.manage_roles or not me.guild_permissions.manage_channels:
        return await interaction.response.send_message(
            "❌ บอทต้องมี Manage Roles และ Manage Channels (ชั่วคราวใช้ Administrator ได้)", ephemeral=True)
    if setup_lock.locked():
        return await interaction.response.send_message("กำลังทำงานอื่นอยู่ กรุณารอให้รอบเดิมจบ", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with setup_lock:
        try:
            _, changes, _, _, _ = privacy_preview_data(interaction.guild)
            if not changes:
                return await interaction.followup.send("✅ สิทธิ์ตรงตามแผนอยู่แล้ว ไม่มีอะไรต้องเปลี่ยน (Backup เดิมยังอยู่)", ephemeral=True)
            backup = privacy_snapshot(interaction.guild)
            count, errors = await privacy_apply_all(interaction.guild)
            out = (f"🔐 ปรับสิทธิ์ InveNOIR v6 แล้ว {count} หมวด/ห้อง\n"
                   f"💾 Backup: {backup}\n"
                   "@everyone เห็นเฉพาะ Welcome; ที่เหลือดูตามยศ\n"
                   "หากอยากย้อนกลับใช้ /privacy_restore confirm:true")
            if errors:
                out += "\n⚠️ บางรายการไม่สำเร็จ:\n" + "\n".join(errors[:6])
                if len(errors) > 6:
                    out += f"\nและอีก {len(errors)-6} จุด"
            await interaction.followup.send(out[:1950], ephemeral=True)
        except Exception as exc:
            traceback.print_exc()
            await interaction.followup.send(
                f"❌ privacy_apply: {type(exc).__name__}: {str(exc)[:350]}", ephemeral=True)


@client.tree.command(name="privacy_restore", description="คืนสิทธิ์เดิมจาก Backup ล่าสุด", guild=TARGET_GUILD)
@app_commands.describe(confirm="true เพื่อคืนค่าที่บันทึกไว้")
async def privacy_restore(interaction: discord.Interaction, confirm: bool):
    if not interaction.guild or interaction.guild.id != GUILD_ID or interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("สำหรับเจ้าของเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
    if not confirm:
        return await interaction.response.send_message("ยังไม่คืนค่า กรุณาเลือก confirm:true", ephemeral=True)
    if setup_lock.locked():
        return await interaction.response.send_message("บอทยังทำงานอื่นอยู่", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with setup_lock:
        try:
            count, errors = await privacy_restore_all(interaction.guild)
            msg = f"↩️ คืนสิทธิ์จาก Backup แล้ว {count} ห้อง/หมวด"
            if errors:
                msg += "\n⚠️ บางจุดไม่สำเร็จ:\n" + "\n".join(errors[:7])
            await interaction.followup.send(msg[:1950], ephemeral=True)
        except Exception as exc:
            traceback.print_exc()
            await interaction.followup.send(f"❌ privacy_restore: {type(exc).__name__}: {str(exc)[:250]}", ephemeral=True)


# ------------------------------------------------------------
# v7 - public role picker, gated introductions, safe Finder cleanup.
# ------------------------------------------------------------

def member_roles_check(guild):
    _, issue = self_roles_safe(guild)
    if issue:
        return issue
    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        return "บอทต้องมี Manage Channels"
    return None


def cleanup_targets(guild):
    cat = finder_category(guild)
    if cat is None:
        return None, [], "ไม่พบหมวด Team Finder"
    if sum(is_group_finder(c.name) for c in cat.channels) != 1:
        return cat, [], "ต้องมี group-finder เพียง 1 ห้อง จึงจะลบห้องเก่าได้อย่างปลอดภัย"
    if sum(is_team_chat(c.name) for c in cat.channels) != 1:
        return cat, [], "ยังไม่มี team-chat กรุณารัน /onboarding_apply ก่อน"
    if sum(is_member_profiles(c.name) for c in cat.channels) > 1:
        return cat, [], "พบ member-profiles มากกว่า 1 ห้อง กรุณาตรวจสอบด้วยตนเองก่อนลบห้องเก่า"
    candidates = [ch for ch in cat.channels if not (
        is_group_finder(ch.name) or is_team_chat(ch.name) or is_member_profiles(ch.name))]
    return cat, candidates, None


TEAM_ROOMS_CATEGORY_NAME = "✧ Team Rooms 🔒"
FULL_TEAM_APPLICATIONS_CHANNEL_NAME = "📨・full-team-applications"  # Legacy v12/v13 channel; retained for old applications.
REGISTERED_TEAMS_CATEGORY_NAME = "✧ Registered Teams 🔒"
TEAM_REGISTRATION_REVIEW_CHANNEL_NAME = "📨・team-registration-review"


def registration_review_channel(guild):
    return next((c for c in guild.text_channels if room_key(c.name) == "team-registration-review"), None)


def registered_teams_category(guild):
    return next((c for c in guild.categories if privacy_category_type(c.name) == "registeredteams"), None)


async def ensure_registered_teams_category(guild):
    """Private category for competition teams; separate from Group Finder team rooms."""
    overwrites = {guild.default_role: discord.PermissionOverwrite(
        view_channel=False, send_messages=False, read_message_history=False)}
    for role_name in ("Organizer", "Staff", "Admin", "Administrator"):
        role = by_name(guild.roles, role_name)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False,
                send_messages_in_threads=False)
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            manage_channels=True, manage_messages=True)
    category = registered_teams_category(guild)
    if category is None:
        category = await guild.create_category(
            REGISTERED_TEAMS_CATEGORY_NAME, overwrites=overwrites,
            reason="InveNOIR v15 private competition registration rooms")
    else:
        await category.edit(overwrites=overwrites, reason="InveNOIR v15 secure competition registration rooms")
    return category


def full_team_applications_channel(guild):
    return next((c for c in guild.text_channels if room_key(c.name) == "full-team-applications"), None)


def registration_text_channel(guild):
    return next((c for c in guild.text_channels if room_key(c.name) == "registration"), None)


def team_rooms_category(guild):
    return next((c for c in guild.categories if privacy_category_type(c.name) == "teamrooms"), None)


async def ensure_team_rooms_category(guild):
    """Create/secure a category for per-team private text channels."""
    overwrites = {guild.default_role: discord.PermissionOverwrite(
        view_channel=False, send_messages=False, read_message_history=False)}
    for role_name in ("Organizer", "Staff"):
        role = by_name(guild.roles, role_name)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False,
                send_messages_in_threads=False)
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            manage_channels=True, manage_messages=True, manage_threads=True)
    category = team_rooms_category(guild)
    if category is None:
        category = await guild.create_category(
            TEAM_ROOMS_CATEGORY_NAME, overwrites=overwrites,
            reason="InveNOIR v15 Group Finder private team rooms")
    else:
        await category.edit(overwrites=overwrites, reason="InveNOIR v15 secure Group Finder private team rooms")
    return category


async def ensure_full_team_applications_channel(guild):
    """Ensure the waitlist intake channel is visible only to Organizer/Staff/Admin."""
    category = next((c for c in guild.categories if privacy_category_type(c.name) == "staff"), None)
    if category is None:
        cat_overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        for role_name in ("Organizer", "Staff", "Admin", "Administrator"):
            role = by_name(guild.roles, role_name)
            if role is not None:
                cat_overwrites[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
        if guild.me is not None:
            cat_overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True)
        category = await guild.create_category("✧ Staff Only 🔒", overwrites=cat_overwrites,
                                               reason="InveNOIR v12.2 staff review category")
    overwrites = {guild.default_role: discord.PermissionOverwrite(
        view_channel=False, send_messages=False, read_message_history=False)}
    allowed_staff_ids = set()
    for role_name in ("Organizer", "Staff", "Admin", "Administrator"):
        role = by_name(guild.roles, role_name)
        if role is not None:
            allowed_staff_ids.add(role.id)
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=True,
                embed_links=True, attach_files=True)
    # Explicitly deny all other non-admin roles, including Judge and competitors.
    # Server Administrators retain access because Discord Administrator bypasses channel overwrites.
    for role in guild.roles:
        if role.is_default() or role.id in allowed_staff_ids:
            continue
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=False, send_messages=False, read_message_history=False)
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, attach_files=True, manage_messages=True)
    channel = full_team_applications_channel(guild)
    if channel is None:
        channel = await guild.create_text_channel(
            FULL_TEAM_APPLICATIONS_CHANNEL_NAME, category=category,
            topic="ห้องเก่าของใบสมัครสำรอง — ย้ายไป Team Registration ได้โดยไม่ลบข้อความเดิม",
            overwrites=overwrites, reason="InveNOIR v13 private full-team applications")
    else:
        await channel.edit(category=category, overwrites=overwrites,
                           topic="ห้องเก่าของใบสมัครสำรอง — ย้ายไป Team Registration ได้โดยไม่ลบข้อความเดิม",
                           reason="InveNOIR v13 secure full-team application channel")
    return channel


async def ensure_team_registration_review_channel(guild):
    """Create or safely migrate the staff-only review channel for official team entries."""
    category = next((c for c in guild.categories if privacy_category_type(c.name) == "staff"), None)
    if category is None:
        cat_overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        for role_name in ("Organizer", "Staff", "Admin", "Administrator"):
            role = by_name(guild.roles, role_name)
            if role is not None:
                cat_overwrites[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
        if guild.me is not None:
            cat_overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=True)
        category = await guild.create_category("✧ Staff Only 🔒", overwrites=cat_overwrites,
                                               reason="InveNOIR v15 team registration review")
    overwrites = {guild.default_role: discord.PermissionOverwrite(
        view_channel=False, send_messages=False, read_message_history=False)}
    allowed_staff_ids = set()
    for role_name in ("Organizer", "Staff", "Admin", "Administrator"):
        role = by_name(guild.roles, role_name)
        if role is not None:
            allowed_staff_ids.add(role.id)
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=True,
                embed_links=True, attach_files=True)
    for role in guild.roles:
        if role.is_default() or role.id in allowed_staff_ids:
            continue
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=False, send_messages=False, read_message_history=False)
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, attach_files=True, manage_messages=True)
    channel = registration_review_channel(guild)
    if channel is None:
        # Migrate the old v12/v13 staff-only waitlist room without deleting its messages.
        channel = full_team_applications_channel(guild)
        if channel is not None:
            await channel.edit(
                name=TEAM_REGISTRATION_REVIEW_CHANNEL_NAME, category=category,
                topic="ใบสมัครทีมเข้าแข่งขันอย่างเป็นทางการ — Organizer / Staff / Administrator เท่านั้น",
                overwrites=overwrites, reason="InveNOIR v15 migrate legacy staff application room")
    if channel is None:
        channel = await guild.create_text_channel(
            TEAM_REGISTRATION_REVIEW_CHANNEL_NAME, category=category,
            topic="ใบสมัครทีมเข้าแข่งขันอย่างเป็นทางการ — Organizer / Staff / Administrator เท่านั้น",
            overwrites=overwrites, reason="InveNOIR v15 private team registration review")
    else:
        await channel.edit(
            category=category, overwrites=overwrites,
            topic="ใบสมัครทีมเข้าแข่งขันอย่างเป็นทางการ — Organizer / Staff / Administrator เท่านั้น",
            reason="InveNOIR v15 secure team registration review")
    return channel


async def ensure_rooms(guild):
    made = []
    cat = welcome_category(guild)
    if cat is None:
        raise ValueError("ไม่พบหมวด Welcome")
    selector = choose_channel(guild)
    if selector is None:
        selector = await guild.create_text_channel(
            "🎭・choose-your-role", category=cat,
            topic="คนเข้าใหม่กดรับยศที่นี่ก่อนเห็นห้องสมาชิก",
            overwrites=privacy_overwrites_for_new(guild, cat.name, "🎭・choose-your-role"),
            reason="InveNOIR v7 public self-role onboarding")
        made.append(selector.name)
    cat_finder = finder_category(guild)
    if cat_finder is None:
        raise ValueError("ไม่พบหมวด Team Finder")
    # Accept an existing text channel OR forum channel named group-finder.
    # Create a Forum only when no usable text/forum channel exists.
    if team_finder_forum(guild) is None:
        forum = await guild.create_forum(
            "🔎・group-finder", topic="ประกาศหาทีมและรับสมาชิกเข้าร่วม Chorus Battle",
            category=cat_finder,
            overwrites=privacy_overwrites_for_new(guild, cat_finder.name, "🔎・group-finder"),
            reason="InveNOIR v12 group finder")
        made.append(forum.name)
    if not any(is_member_profiles(c.name) for c in cat_finder.channels):
        profiles = await guild.create_text_channel(
            "👤・member-profiles", topic="สร้างโปรไฟล์ ใส่นามแฝงและลิงก์ผลงาน เพื่อให้ทีมค้นหาสมาชิกที่กำลังหาทีม",
            category=cat_finder,
            overwrites=privacy_overwrites_for_new(guild, cat_finder.name, "👤・member-profiles"),
            reason="InveNOIR v12 member profile directory")
        made.append(profiles.name)
    if not any(is_team_chat(c.name) for c in cat_finder.channels):
        chat = await guild.create_text_channel(
            "💬・team-chat", topic="แชทรวมสำหรับทุกคนที่รับยศแล้ว",
            category=cat_finder,
            overwrites=privacy_overwrites_for_new(guild, cat_finder.name, "💬・team-chat"),
            reason="InveNOIR v7 shared team chat")
        made.append(chat.name)
    # v16 keeps Group Finder private team rooms only; official Team Registration is retired.
    await ensure_team_rooms_category(guild)
    return made


@client.tree.command(name="onboarding_preview", description="ดูแผนห้องรับยศและเปิดแชทเฉพาะสมาชิก", guild=TARGET_GUILD)
async def onboarding_preview(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของ/Administrator", ephemeral=True)
    targets, changes, _, _, _ = privacy_preview_data(interaction.guild)
    msg = (
        "🎭 InveNOIR v7 — PREVIEW (ยังไม่เปลี่ยนอะไร)\n"
        "ไม่มียศ: เห็น Welcome/ประกาศ/กฎ/ข้อมูล/choose-your-role และกดเลือกได้\n"
        "หลังรับยศ: เห็น introduce-yourself, Chorus Battle, Community และ Team Finder\n"
        "Team Finder: เก็บ group-finder + member-profiles + team-chat สำหรับสมาชิกทุกยศ\n"
        "ห้องเก่าใน Team Finder: ซ่อนไว้จากสมาชิกจนกว่าจะสั่งลบแยก\n"
        "Staff Only: ผู้ดูแลเท่านั้น; Judge เห็นเฉพาะห้องกรรมการและส่งผลงาน\n"
        f"ตรวจ {len(targets)} ห้อง/หมวด | สิทธิ์ต้องปรับราว {len(changes)} จุด\n"
        "ใช้ /onboarding_apply confirm:true เพื่อสร้างห้องรับยศ, โพสต์เมนู และตั้งสิทธิ์\n"
        "คำสั่งนี้จะไม่ลบห้อง ต้องใช้ /team_cleanup_preview ก่อนแยกต่างหาก"
    )
    await interaction.response.send_message(msg[:1900], ephemeral=True)


@client.tree.command(name="onboarding_apply", description="ตั้งระบบรับยศก่อนเข้าห้องสมาชิก (ไม่ลบห้อง)", guild=TARGET_GUILD)
@app_commands.describe(confirm="เลือก true เพื่อเปลี่ยนสิทธิ์และสร้างห้องยศ")
async def onboarding_apply(interaction: discord.Interaction, confirm: bool):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของ/Administrator", ephemeral=True)
    if not confirm:
        return await interaction.response.send_message("ต้องยืนยัน confirm:true", ephemeral=True)
    problem = member_roles_check(interaction.guild)
    if problem:
        return await interaction.response.send_message("❌ " + problem, ephemeral=True)
    if setup_lock.locked():
        return await interaction.response.send_message("บอทกำลังทำงานอื่นอยู่", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with setup_lock:
        try:
            backup = privacy_snapshot(interaction.guild)
            made = await ensure_rooms(interaction.guild)
            # Post BEFORE locking member channels, to guarantee a working entry point.
            picker = choose_channel(interaction.guild)
            panel_action = await ensure_role_panel(picker)
            edited, errs = await privacy_apply_all(interaction.guild)
            msg = (
                f"✅ InveNOIR v7 | ห้องใหม่ {len(made)} | เปลี่ยนสิทธิ์ {edited} ห้อง/หมวด\n"
                f"🎭 {panel_action} {picker.mention}\n"
                "สมาชิกที่ไม่มียศเห็น Welcome และกดรับยศได้; พอได้ยศจึงเข้าห้องแนะนำตัว/หาทีม/แชท\n"
                f"💾 สำรองสิทธิ์ก่อนทำไว้ที่: {backup}\n"
                "ยังไม่ได้ลบห้องใด ๆ — ใช้ /team_cleanup_preview แล้วค่อยยืนยันลบ"
            )
            if errs:
                msg += "\n⚠️ ปรับไม่ครบ:\n" + "\n".join(errs[:5])
            await interaction.followup.send(msg[:1900], ephemeral=True)
        except Exception as exc:
            traceback.print_exc()
            await interaction.followup.send(
                f"❌ onboarding_apply: {type(exc).__name__}: {str(exc)[:300]}", ephemeral=True)


@client.tree.command(name="team_cleanup_preview", description="รายชื่อห้อง Team Finder ที่จะถูกลบ (ไม่ลบจริง)", guild=TARGET_GUILD)
async def team_cleanup_preview(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID or interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("คำสั่งลบห้องเฉพาะเจ้าของเซิร์ฟเวอร์", ephemeral=True)
    _, targets, problem = cleanup_targets(interaction.guild)
    if problem:
        return await interaction.response.send_message("❌ " + problem, ephemeral=True)
    msg = (
        "🧹 Team Finder — PREVIEW\n"
        "✅ เก็บ: group-finder, member-profiles (ถ้ามี) และ team-chat\n"
        f"🗑️ ลบ {len(targets)} ห้อง:\n"
        + ("\n".join(f"• {ch.name} ({ch.id})" for ch in targets) or "• ไม่มีห้องต้องลบ")
        + "\n⚠️ การลบห้องทำให้ข้อความและโพสต์ในห้องนั้นหาย กู้คืนด้วย privacy backup ไม่ได้\n"
        + "หากตรวจชื่อถูกแล้ว ใช้ /team_cleanup_apply confirm:true code:DELETE"
    )
    await interaction.response.send_message(msg[:1900], ephemeral=True)


@client.tree.command(name="team_cleanup_apply", description="ลบห้อง Team Finder เก่า (ต้องพิมพ์ DELETE)", guild=TARGET_GUILD)
@app_commands.describe(confirm="true เพื่อยืนยัน", code="พิมพ์ DELETE เมื่อเห็นรายชื่อห้องจาก preview แล้ว")
async def team_cleanup_apply(interaction: discord.Interaction, confirm: bool, code: str):
    if not interaction.guild or interaction.guild.id != GUILD_ID or interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("คำสั่งนี้เฉพาะเจ้าของเซิร์ฟเวอร์", ephemeral=True)
    if not confirm or code != "DELETE":
        return await interaction.response.send_message("ยังไม่ลบ: ต้อง confirm:true และ code:DELETE", ephemeral=True)
    if setup_lock.locked():
        return await interaction.response.send_message("บอทกำลังทำงานอื่นอยู่", ephemeral=True)
    cat, targets, problem = cleanup_targets(interaction.guild)
    if problem:
        return await interaction.response.send_message("❌ " + problem, ephemeral=True)
    if not targets:
        return await interaction.response.send_message("✅ ไม่มีห้องเก่าให้ลบแล้ว (เก็บ group-finder, member-profiles และ team-chat ไว้)", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with setup_lock:
        try:
            # Manifest is metadata-only. Deleted messages/threads cannot be recovered.
            manifest = {
                "guild_id": interaction.guild.id, "created_at": datetime.now(timezone.utc).isoformat(),
                "notice": "Metadata only. Deleted Discord messages cannot be restored.",
                "category": cat.name,
                "planned_deletions": [{"id": ch.id, "name": ch.name, "type": str(ch.type)} for ch in targets],
            }
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            manifest_file = DATA_DIR / f"deleted_team_finder_manifest_{stamp}.json"
            manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            done, errors = [], []
            for ch in targets:
                try:
                    await ch.delete(reason="InveNOIR v12 team cleanup / server owner confirmed DELETE")
                    done.append(ch.name)
                except discord.HTTPException as exc:
                    errors.append(f"{ch.name}: {str(exc)[:150]}")
            msg = (f"🧹 ลบ {len(done)} ห้องสำเร็จ • เก็บ group-finder + member-profiles + team-chat ไว้\n"
                   f"💾 บันทึกรายชื่อห้องก่อนลบ: {manifest_file.name}\n"
                   "⚠️ ข้อความในห้องที่ลบแล้วกู้คืนไม่ได้")
            if errors:
                msg += "\n❌ ลบไม่สำเร็จ:\n" + "\n".join(errors[:5])
            await interaction.followup.send(msg[:1950], ephemeral=True)
        except Exception as exc:
            traceback.print_exc()
            await interaction.followup.send(f"❌ team_cleanup_apply: {type(exc).__name__}: {str(exc)[:250]}", ephemeral=True)


@client.tree.command(name="status", description="ตรวจเวอร์ชันบอท InveNOIR", guild=TARGET_GUILD)
async def status(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์หรือ Administrator", ephemeral=True)
    await interaction.response.send_message(
        f"✅ InveNOIR Bot {VERSION} กำลังทำงาน\nไฟล์: `{Path(__file__).name}`", ephemeral=True)


@client.tree.command(name="preview", description="ดูจำนวนห้อง/ยศที่จะสร้างก่อนยืนยัน", guild=TARGET_GUILD)
async def preview(interaction: discord.Interaction):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์หรือ Administrator", ephemeral=True)
    roles, categories, channels = plan(interaction.guild)
    await interaction.response.send_message(
        f"InveNOIR {VERSION}\n"
        f"จะสร้างเพิ่ม: {len(roles)} ยศ / {len(categories)} หมวด / {len(channels)} ห้อง\n"
        "เลข 0 หมายถึงมีชื่อนี้อยู่แล้ว ไม่ได้หมายความว่าไม่มีในเซิร์ฟเวอร์\n"
        "ไม่ลบ ไม่ย้าย ไม่แก้ห้องหรือยศเดิม\n"
        "สั่ง `/setup confirm:true` เพื่อสร้างเฉพาะที่ขาด", ephemeral=True)


@client.tree.command(name="setup", description="สร้างโครงสร้าง InveNOIR (ไม่ลบของเดิม)", guild=TARGET_GUILD)
@app_commands.describe(confirm="เลือก true เพื่อยืนยัน")
async def setup(interaction: discord.Interaction, confirm: bool):
    if not authorized(interaction):
        return await interaction.response.send_message("เฉพาะเจ้าของเซิร์ฟเวอร์หรือ Administrator", ephemeral=True)
    if not confirm:
        return await interaction.response.send_message("ยังไม่ทำอะไร เลือก confirm:true ก่อน", ephemeral=True)
    if setup_lock.locked():
        return await interaction.response.send_message("บอทกำลังจัดเซิร์ฟเวอร์อยู่ กรุณารอให้รอบก่อนเสร็จ", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with setup_lock:
        try:
            made, errors = await build_server(interaction.guild)
            response = (
                f"✅ InveNOIR {VERSION} ทำงานเสร็จ\n"
                f"เพิ่ม: {made['roles']} ยศ, {made['categories']} หมวด, {made['channels']} ห้อง"
            )
            if errors:
                response += "\n⚠️ ข้อที่ยังไม่สำเร็จ:\n" + "\n".join(errors[:8])
                if len(errors) > 8:
                    response += f"\nและอีก {len(errors) - 8} ข้อ ดูรายละเอียดในหน้าต่างบอท"
            await interaction.followup.send(response[:1900], ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            await interaction.followup.send(
                f"❌ บอท {VERSION} พบข้อผิดพลาด: {type(e).__name__}: {str(e)[:400]}\n"
                "ส่งข้อความนี้และบรรทัด Error ในหน้าต่างบอทมาได้เลย", ephemeral=True)


# ============================================================
# Announcement Manager v9 (manual / scheduled / recurring)
# - Not enabled for automatic posting until staff explicitly schedules it.
# - Never performs mass pings by default; optional one role mention.
# - Stored locally in JSON. Bot must be running at due time (or restarted).
# - "sending" is committed BEFORE sending to avoid silent duplicates.
# ============================================================
STOCKHOLM = ZoneInfo("Europe/Stockholm")
ANNOUNCE_FILE = DATA_DIR / "announcements_jobs.json"
ANNOUNCE_LOCK = asyncio.Lock()
MAX_ACTIVE_ANNOUNCEMENTS = 80
ANNOUNCE_KIND_LABELS = {
    "general": ("📢 ข่าวสาร", 0x9C80DD),
    "registration": ("📝 เปิดรับสมัคร", 0x64BDA0),
    "theme": ("🎭 เผยธีมการแข่งขัน", 0xC28AE8),
    "deadline": ("⏰ เตือนกำหนดส่งผลงาน", 0xEDA64E),
    "results": ("🏆 ผลการแข่งขัน", 0xE8C563),
}
ANNOUNCE_REPEAT_LABELS = {"once": "ครั้งเดียว", "daily": "ทุกวัน", "weekly": "ทุกสัปดาห์"}


def can_announce(interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID:
        return False
    if authorized(interaction):
        return True
    member = interaction.user
    return isinstance(member, discord.Member) and any(
        r.name in {"Organizer", "Staff"} for r in member.roles
    )


def announcement_room(guild, room=None):
    if room is not None:
        return room if room.guild.id == guild.id else None
    return next((c for c in guild.text_channels if room_key(c.name) == "announcements"), None)


def announcement_embed(title, message, kind="general", image_url=None):
    label, color = ANNOUNCE_KIND_LABELS.get(kind, ANNOUNCE_KIND_LABELS["general"])
    embed = discord.Embed(
        title=title.strip(),
        description=message.strip(),
        colour=discord.Colour(color),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=f"InveNOIR Chorus Battle | {label}")
    embed.set_footer(text="InveNOIR • Official Announcement")
    if image_url:
        embed.set_image(url=image_url)
    return embed


def announcement_validate(title, message, image_url=None):
    if not title or not title.strip() or len(title) > 200:
        return "หัวข้อต้องมี 1–200 ตัวอักษร"
    if not message or not message.strip() or len(message) > 3800:
        return "เนื้อหาต้องมี 1–3,800 ตัวอักษร"
    if image_url:
        try:
            u = urlparse(image_url)
            if u.scheme != "https" or not u.hostname or len(image_url) > 1500:
                return "ลิงก์รูปภาพต้องเป็น HTTPS URL ที่ถูกต้อง"
        except ValueError:
            return "รูปแบบลิงก์ภาพไม่ถูกต้อง"
    return None


def safe_announcement_mentions(role=None):
    # No @everyone/@here or incidental user/role ping from title or description.
    return discord.AllowedMentions(
        everyone=False, users=False, roles=[role] if role else False, replied_user=False
    )


def channel_send_problem(guild, channel):
    if channel is None:
        return "ไม่พบห้อง announcements — เลือกห้องเป้าหมายเองหรือตรวจสอบชื่อห้อง"
    me = guild.me
    if me is None:
        return "ไม่พบข้อมูลยศบอท กรุณาลองใหม่"
    p = channel.permissions_for(me)
    if not p.view_channel or not p.send_messages or not p.embed_links:
        return f"บอทต้องมี View Channel, Send Messages และ Embed Links ใน {channel.mention}"
    return None


def parse_local_announcement_datetime(text_value, now_utc=None):
    """YYYY-MM-DD HH:MM Europe/Stockholm -> UTC datetime; reject DST skipped wall times."""
    try:
        naive = datetime.strptime(text_value.strip(), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("กรอกเวลาเป็น YYYY-MM-DD HH:MM เช่น 2026-11-01 19:00") from exc
    aware = naive.replace(tzinfo=STOCKHOLM, fold=0)
    utc_dt = aware.astimezone(timezone.utc)
    if utc_dt.astimezone(STOCKHOLM).replace(tzinfo=None) != naive:
        raise ValueError("เวลานี้ไม่มีอยู่จริงเพราะการปรับเวลาในสวีเดน กรุณาเลือกเวลาใหม่")
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if utc_dt <= now_utc + timedelta(seconds=30):
        raise ValueError("เวลาโพสต์ต้องอยู่ในอนาคตอย่างน้อย 30 วินาที")
    if utc_dt > now_utc + timedelta(days=365):
        raise ValueError("ตั้งเวลาล่วงหน้าได้ไม่เกิน 365 วัน")
    return utc_dt


def next_occurrence(current_utc, repeat, now_utc=None):
    """Keep Swedish *local clock time* unchanged across DST transitions."""
    if repeat not in {"daily", "weekly"}:
        return None
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    current_local = current_utc.astimezone(STOCKHOLM)
    date = current_local.date()
    clock = current_local.time().replace(tzinfo=None)
    step = timedelta(days=1 if repeat == "daily" else 7)
    for _ in range(400):
        date += step
        next_local = datetime.combine(date, clock, tzinfo=STOCKHOLM)
        next_utc = next_local.astimezone(timezone.utc)
        # At DST spring transition a local 02:30 may not exist; normalize forward.
        next_local = next_utc.astimezone(STOCKHOLM)
        next_utc = next_local.astimezone(timezone.utc)
        if next_utc > now_utc:
            return next_utc
    raise ValueError("หาวันประกาศครั้งต่อไปไม่ได้")


def announce_load_jobs():
    if not ANNOUNCE_FILE.exists():
        return []
    data = json.loads(ANNOUNCE_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("announcements_jobs.json มีรูปแบบไม่ถูกต้อง")
    return data["jobs"]


def announce_save_jobs(jobs):
    # Atomic write on local NTFS / POSIX to reduce truncation after interruption.
    payload = {"format": 1, "jobs": jobs}
    temp = ANNOUNCE_FILE.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, ANNOUNCE_FILE)


def to_local_time(utc_iso):
    dt = datetime.fromisoformat(utc_iso)
    return dt.astimezone(STOCKHOLM).strftime("%d/%m/%Y %H:%M")


@client.tree.command(name="announce_preview", description="ดูตัวอย่างประกาศสวย ๆ ก่อนส่งจริง", guild=TARGET_GUILD)
@app_commands.describe(title="หัวข้อประกาศ", message="เนื้อหาประกาศ", kind="ประเภทประกาศ", image_url="URL ภาพประกอบ (ไม่บังคับ)")
async def announce_preview(
    interaction: discord.Interaction,
    title: str,
    message: str,
    kind: Literal["general", "registration", "theme", "deadline", "results"] = "general",
    image_url: str | None = None,
):
    if not can_announce(interaction):
        return await interaction.response.send_message("❌ เฉพาะเจ้าของเซิร์ฟเวอร์, Administrator, Organizer หรือ Staff", ephemeral=True)
    invalid = announcement_validate(title, message, image_url)
    if invalid:
        return await interaction.response.send_message("❌ " + invalid, ephemeral=True)
    await interaction.response.send_message(
        "ตัวอย่างเท่านั้น ยังไม่ได้ประกาศ", embed=announcement_embed(title, message, kind, image_url),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )


@client.tree.command(name="announce_send", description="ส่งประกาศ Embed สวย ๆ ไปยังห้องที่เลือกทันที", guild=TARGET_GUILD)
@app_commands.describe(title="หัวข้อประกาศ", message="เนื้อหา", channel="ห้องที่จะประกาศ (ว่างไว้ใช้ announcements)", kind="ประเภทประกาศ", image_url="URL รูป (ไม่บังคับ)", mention_role="เลือกยศที่ต้องการแจ้งเตือน (ไม่บังคับ)")
async def announce_send(
    interaction: discord.Interaction,
    title: str,
    message: str,
    channel: discord.TextChannel | None = None,
    kind: Literal["general", "registration", "theme", "deadline", "results"] = "general",
    image_url: str | None = None,
    mention_role: discord.Role | None = None,
):
    if not can_announce(interaction):
        return await interaction.response.send_message("❌ ไม่มีสิทธิ์ส่งประกาศ", ephemeral=True)
    invalid = announcement_validate(title, message, image_url)
    if invalid:
        return await interaction.response.send_message("❌ " + invalid, ephemeral=True)
    if mention_role and (mention_role.is_default() or mention_role.guild.id != GUILD_ID):
        return await interaction.response.send_message("❌ ไม่รองรับการแจ้งเตือน @everyone", ephemeral=True)
    destination = announcement_room(interaction.guild, channel)
    problem = channel_send_problem(interaction.guild, destination)
    if problem:
        return await interaction.response.send_message("❌ " + problem, ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        msg = await destination.send(
            content=mention_role.mention if mention_role else None,
            embed=announcement_embed(title, message, kind, image_url),
            allowed_mentions=safe_announcement_mentions(mention_role),
        )
        await interaction.followup.send(f"✅ ส่งประกาศแล้วใน {destination.mention}: {msg.jump_url}", ephemeral=True)
    except discord.HTTPException as exc:
        await interaction.followup.send(f"❌ ส่งไม่ได้: {str(exc)[:350]}", ephemeral=True)


@client.tree.command(name="announce_schedule", description="ตั้งเวลาโพสต์ประกาศครั้งเดียว ทุกวัน หรือทุกสัปดาห์", guild=TARGET_GUILD)
@app_commands.describe(title="หัวข้อประกาศ", message="ข้อความ", when="วันที่เวลาแบบสวีเดน YYYY-MM-DD HH:MM", repeat="ครั้งเดียว / ทุกวัน / ทุกสัปดาห์", channel="ห้องที่ต้องการ (ว่างไว้ใช้ announcements)", kind="ประเภท", image_url="รูป HTTPS (ไม่บังคับ)", mention_role="ยศที่จะ Ping (ไม่บังคับ)")
async def announce_schedule(
    interaction: discord.Interaction,
    title: str,
    message: str,
    when: str,
    repeat: Literal["once", "daily", "weekly"] = "once",
    channel: discord.TextChannel | None = None,
    kind: Literal["general", "registration", "theme", "deadline", "results"] = "general",
    image_url: str | None = None,
    mention_role: discord.Role | None = None,
):
    if not can_announce(interaction):
        return await interaction.response.send_message("❌ ไม่มีสิทธิ์ตั้งประกาศ", ephemeral=True)
    invalid = announcement_validate(title, message, image_url)
    if invalid:
        return await interaction.response.send_message("❌ " + invalid, ephemeral=True)
    if mention_role and (mention_role.is_default() or mention_role.guild.id != GUILD_ID):
        return await interaction.response.send_message("❌ ไม่รองรับ @everyone", ephemeral=True)
    destination = announcement_room(interaction.guild, channel)
    problem = channel_send_problem(interaction.guild, destination)
    if problem:
        return await interaction.response.send_message("❌ " + problem, ephemeral=True)
    try:
        when_utc = parse_local_announcement_datetime(when)
    except ValueError as exc:
        return await interaction.response.send_message("❌ " + str(exc), ephemeral=True)
    async with ANNOUNCE_LOCK:
        try:
            jobs = announce_load_jobs()
            if sum(j.get("status") == "pending" for j in jobs) >= MAX_ACTIVE_ANNOUNCEMENTS:
                return await interaction.response.send_message("❌ มีประกาศที่ตั้งเวลาไว้เต็มแล้ว (80 รายการ)", ephemeral=True)
            id_value = max((int(j["id"]) for j in jobs), default=0) + 1
            jobs.append({
                "id": id_value, "title": title.strip(), "message": message.strip(),
                "kind": kind, "image_url": image_url, "channel_id": destination.id,
                "role_id": mention_role.id if mention_role else None,
                "repeat": repeat, "next_utc": when_utc.isoformat(), "status": "pending",
                "created_by": interaction.user.id, "created_utc": datetime.now(timezone.utc).isoformat(),
            })
            announce_save_jobs(jobs)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ บันทึกประกาศไม่ได้: {str(exc)[:250]}", ephemeral=True)
    await interaction.response.send_message(
        f"✅ ตั้งประกาศ #{id_value} แล้ว\n"
        f"**{title.strip()}** → {destination.mention}\n"
        f"📅 {to_local_time(when_utc.isoformat())} (เวลา Sweden) • {ANNOUNCE_REPEAT_LABELS[repeat]}\n"
        "⚠️ บอทต้องเปิดทำงานไว้ตอนถึงเวลาส่ง", ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@client.tree.command(name="announce_list", description="ดูประกาศที่ตั้งเวลาและสถานะ", guild=TARGET_GUILD)
async def announce_list(interaction: discord.Interaction):
    if not can_announce(interaction):
        return await interaction.response.send_message("❌ ไม่มีสิทธิ์ดูประกาศที่ตั้งเวลา", ephemeral=True)
    async with ANNOUNCE_LOCK:
        try:
            jobs = announce_load_jobs()
        except (OSError, ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ อ่านรายการไม่ได้: {exc}", ephemeral=True)
    if not jobs:
        return await interaction.response.send_message("📭 ยังไม่มีประกาศที่ตั้งเวลา", ephemeral=True)
    pending = sorted((j for j in jobs if j.get("status") == "pending"), key=lambda j: j["next_utc"])
    historical = [j for j in jobs if j.get("status") != "pending"][-5:]
    display = pending[:20] + historical
    symbols = {"pending": "🕒", "sent": "✅", "failed": "❌", "cancelled": "🚫", "missed": "⌛", "interrupted": "⚠️", "sending": "📤"}
    lines = []
    for j in display:
        title_short = str(j.get("title", ""))[:52].replace("`", "'")
        try:
            at = to_local_time(j["next_utc"])
        except (KeyError, ValueError):
            at = "-"
        lines.append(f"{symbols.get(j.get('status'), '•')} **#{j['id']}** {title_short} — {at} — {ANNOUNCE_REPEAT_LABELS.get(j.get('repeat'), 'ครั้งเดียว')}")
    remainder = max(0, len(pending) - 20)
    if remainder:
        lines.append(f"…และอีก {remainder} รายการที่กำลังรอส่ง")
    await interaction.response.send_message("📢 **InveNOIR Scheduled Announcements**\n" + "\n".join(lines)[:1700], ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="announce_cancel", description="ยกเลิกประกาศที่ตั้งเวลาด้วยเลข ID", guild=TARGET_GUILD)
@app_commands.describe(announcement_id="เลข # จาก announce_list")
async def announce_cancel(interaction: discord.Interaction, announcement_id: int):
    if not can_announce(interaction):
        return await interaction.response.send_message("❌ ไม่มีสิทธิ์ยกเลิก", ephemeral=True)
    async with ANNOUNCE_LOCK:
        try:
            jobs = announce_load_jobs()
            target = next((j for j in jobs if j.get("id") == announcement_id), None)
            if target is None:
                message = "❌ ไม่พบเลขประกาศนี้"
            elif target.get("status") != "pending":
                message = "❌ รายการนี้ไม่อยู่ในสถานะรอส่งแล้ว"
            else:
                target["status"] = "cancelled"
                announce_save_jobs(jobs)
                message = f"✅ ยกเลิกประกาศ #{announcement_id} แล้ว"
        except (OSError, ValueError, TypeError) as exc:
            message = f"❌ ยกเลิกไม่ได้: {str(exc)[:250]}"
    await interaction.response.send_message(message, ephemeral=True)


@tasks.loop(seconds=30)
async def announcement_worker():
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        return
    now = datetime.now(timezone.utc)
    # Claim maximum 3 due jobs per pass; commit before network send to avoid duplicates.
    async with ANNOUNCE_LOCK:
        try:
            jobs = announce_load_jobs()
            for j in jobs:
                if j.get("status") == "sending":
                    j["status"] = "interrupted"
                    print(f"[InveNOIR Announcements] #{j.get('id')}: uncertain send after restart; inspect manually", flush=True)
            pending = sorted((j for j in jobs if j.get("status") == "pending" and datetime.fromisoformat(j["next_utc"]) <= now),
                             key=lambda j: j["next_utc"])[:3]
            for j in pending:
                lateness = now - datetime.fromisoformat(j["next_utc"])
                if lateness > timedelta(hours=12):
                    if j.get("repeat") in ("daily", "weekly"):
                        j["next_utc"] = next_occurrence(datetime.fromisoformat(j["next_utc"]), j["repeat"], now).isoformat()
                    else:
                        j["status"] = "missed"
                else:
                    j["status"] = "sending"
            announce_save_jobs(jobs)
            claimed = [dict(j) for j in pending if j["status"] == "sending"]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f"[InveNOIR Announcements] job file error: {exc!r}", flush=True)
            return
    for job in claimed:
        error = None
        sent_url = None
        try:
            room = guild.get_channel(int(job["channel_id"]))
            if not isinstance(room, discord.TextChannel):
                raise ValueError("ห้องประกาศหายไปแล้ว")
            problem = channel_send_problem(guild, room)
            if problem:
                raise ValueError(problem)
            role = guild.get_role(int(job["role_id"])) if job.get("role_id") else None
            msg = await room.send(
                content=role.mention if role else None,
                embed=announcement_embed(job["title"], job["message"], job.get("kind", "general"), job.get("image_url")),
                allowed_mentions=safe_announcement_mentions(role),
            )
            sent_url = msg.jump_url
            print(f"[InveNOIR Announcements] Sent #{job['id']} -> {room.name}", flush=True)
        except (discord.HTTPException, ValueError, TypeError) as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            print(f"[InveNOIR Announcements] FAILED #{job['id']}: {error}", flush=True)
        async with ANNOUNCE_LOCK:
            try:
                jobs = announce_load_jobs()
                actual = next((j for j in jobs if j.get("id") == job["id"]), None)
                if actual is None or actual.get("status") != "sending":
                    continue
                if error:
                    actual["status"] = "failed"
                    actual["last_error"] = error
                elif job.get("repeat") in ("daily", "weekly"):
                    actual["last_sent_url"] = sent_url
                    actual["next_utc"] = next_occurrence(
                        datetime.fromisoformat(actual["next_utc"]), actual["repeat"], datetime.now(timezone.utc)
                    ).isoformat()
                    actual["status"] = "pending"
                else:
                    actual["status"] = "sent"
                    actual["last_sent_url"] = sent_url
                announce_save_jobs(jobs)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                print(f"[InveNOIR Announcements] Could not store send result for #{job['id']}: {exc!r}", flush=True)


@announcement_worker.before_loop
async def before_announcement_worker():
    await client.wait_until_ready()


# ============================================================
# Team Finder v12 — member profiles, portfolio links, team roster, solo applications/invitations.
# Stored in team_finder_data.json; does not alter roles or channel permissions.
# ============================================================
TEAM_FINDER_FILE = DATA_DIR / "team_finder_data.json"
TEAM_FINDER_LOCK = asyncio.Lock()
TEAM_ACTIVE_STATUSES = {"recruiting", "full"}
TEAM_STATUS_INFO = {
    "recruiting": ("🟢 กำลังรับสมาชิก", 0x59B889),
    "full": ("🔴 ทีมเต็มแล้ว", 0xD96B73),
    "closed": ("⚫ ปิดรับสมัคร", 0x858B98),
}
TEAM_FINDER_PANEL_NAME = "📌 START HERE • Team Finder"
TEAM_ROLE_NAMES = set(COMPETITORS)


def team_data_default():
    return {"teams": [], "applications": [], "full_team_applications": [], "profiles": [], "invitations": [],
            "competition_registrations": [],
            "next_application_id": 1, "next_invitation_id": 1, "next_full_team_application_id": 1,
            "next_competition_registration_id": 1,
            "board_thread_id": None, "board_message_id": None,
            "profile_board_channel_id": None, "profile_board_message_id": None,
            "registration_panel_channel_id": None, "registration_panel_message_id": None}


def team_data_load():
    if not TEAM_FINDER_FILE.exists():
        return team_data_default()
    raw = json.loads(TEAM_FINDER_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("team_finder_data.json ต้องเป็น JSON object")
    data = team_data_default()
    data.update(raw)
    for key in ("teams", "applications", "full_team_applications", "profiles", "invitations", "competition_registrations"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"ข้อมูล {key} ใน team_finder_data.json ไม่ถูกต้อง")
    return data


def team_data_save(data):
    temp = TEAM_FINDER_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(TEAM_FINDER_FILE)


def team_get(data, thread_id):
    return next((t for t in data["teams"] if int(t.get("thread_id", 0)) == int(thread_id)), None)


def team_get_application(data, application_id):
    return next((a for a in data["applications"] if int(a.get("id", 0)) == int(application_id)), None)


def team_get_full_application(data, application_id):
    return next((a for a in data.get("full_team_applications", [])
                 if int(a.get("id", 0)) == int(application_id)), None)


def team_status_text(status):
    return TEAM_STATUS_INFO.get(status, TEAM_STATUS_INFO["closed"])[0]


def team_is_eligible(member):
    if not isinstance(member, discord.Member):
        return False
    return any(r.name in TEAM_ROLE_NAMES or r.name in MODERATORS for r in member.roles)


def team_can_manage(member, team, allow_staff=True):
    if member.id == int(team.get("owner_id", 0)):
        return True
    if not allow_staff or not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True
    return any(r.name in MODERATORS for r in member.roles)


def team_finder_forum(guild):
    """Return the Group Finder Forum or text channel, supporting existing servers."""
    return next((c for c in guild.channels
                 if isinstance(c, (discord.ForumChannel, discord.TextChannel)) and is_group_finder(c.name)), None)


async def create_team_finder_thread(channel, name, content, embeds, view, reason):
    """Create a team/panel post in a Forum, or a public thread inside a text channel."""
    if isinstance(channel, discord.ForumChannel):
        created = await channel.create_thread(
            name=name[:100], content=content, embeds=embeds, view=view,
            auto_archive_duration=10080, reason=reason,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return created.thread, created.message
    if isinstance(channel, discord.TextChannel):
        starter = await channel.send(
            content=f"🧵 **{name[:90]}** — เปิดกระทู้นี้เพื่อดูรายละเอียดและใช้ปุ่มของบอท",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        thread = None
        try:
            thread = await starter.create_thread(
                name=name[:100], auto_archive_duration=10080, reason=reason,
            )
            message = await thread.send(
                content=content, embeds=embeds, view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return thread, message
        except Exception:
            if thread is not None:
                try:
                    await thread.delete(reason="InveNOIR could not finish creating the Team Finder post")
                except (discord.HTTPException, discord.Forbidden):
                    pass
            try:
                await starter.delete()
            except (discord.HTTPException, discord.Forbidden):
                pass
            raise
    raise TypeError("group-finder ต้องเป็น Forum Channel หรือ Text Channel")


def team_chat_text_channel(guild):
    # This is the shared public chat, not where private team conversations are created.
    return next((c for c in guild.text_channels if is_team_chat(c.name)), None)


def is_staff_or_admin(member):
    if not isinstance(member, discord.Member):
        return False
    review_roles = {"Organizer", "Staff", "Admin", "Administrator"}
    return (member.id == member.guild.owner_id or member.guild_permissions.administrator
            or any(r.name in review_roles for r in member.roles))


def profile_get(data, user_id):
    return next((p for p in data.get("profiles", []) if int(p.get("user_id", 0)) == int(user_id)), None)


def team_get_invitation(data, invitation_id):
    return next((inv for inv in data.get("invitations", []) if int(inv.get("id", 0)) == int(invitation_id)), None)


def member_active_team(data, user_id, exclude_thread_id=None):
    user_id = int(user_id)
    for team in data.get("teams", []):
        if team.get("status") not in TEAM_ACTIVE_STATUSES:
            continue
        thread_id = int(team.get("thread_id", 0))
        if exclude_thread_id is not None and thread_id == int(exclude_thread_id):
            continue
        if int(team.get("owner_id", 0)) == user_id or user_id in {int(x) for x in team.get("accepted_members", [])}:
            return team
    return None


def profile_parse_links(raw):
    links = [line.strip() for line in str(raw or "").splitlines() if line.strip()]
    if len(links) > 5:
        return None, "ใส่ลิงก์ผลงานได้สูงสุด 5 ลิงก์ โดยใส่ลิงก์ละ 1 บรรทัด"
    for link in links:
        parsed = urlparse(link)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None, f"ลิงก์ไม่ถูกต้อง: {link[:100]} — กรุณาใช้ลิงก์ที่ขึ้นต้นด้วย https:// หรือ http://"
    return links, None


def profile_validate_fields(alias, specialties, links_text, intro, genres_availability):
    if not alias or not alias.strip() or len(alias.strip()) > 60:
        return "นามแฝงต้องมี 1–60 ตัวอักษร"
    if not specialties or not specialties.strip() or len(specialties.strip()) > 180:
        return "กรอกสายงาน/ทักษะอย่างน้อย 1 อย่าง (ไม่เกิน 180 ตัวอักษร)"
    if not intro or not intro.strip() or len(intro.strip()) > 700:
        return "แนะนำตัวสั้น ๆ ต้องมี 1–700 ตัวอักษร"
    if not genres_availability or not genres_availability.strip() or len(genres_availability.strip()) > 200:
        return "กรอกแนวเพลงหรือเวลาที่สะดวก (ไม่เกิน 200 ตัวอักษร)"
    _, link_error = profile_parse_links(links_text)
    return link_error


def profile_embed(profile, member=None):
    alias = str(profile.get("alias", "Member"))[:80]
    embed = discord.Embed(
        title=f"🪪 {alias}",
        description=str(profile.get("intro", ""))[:3000],
        colour=discord.Colour(0x9C80DD),
        timestamp=datetime.now(timezone.utc),
    )
    if member is not None:
        embed.set_author(name=f"Discord: {member.display_name}", icon_url=member.display_avatar.url)
    embed.add_field(name="🎭 สายงาน / ทักษะ", value=str(profile.get("specialties", "ยังไม่ระบุ"))[:1024], inline=False)
    embed.add_field(name="🎶 แนวเพลง / เวลาที่สะดวก", value=str(profile.get("genres_availability", "ยังไม่ระบุ"))[:1024], inline=False)
    links = profile.get("portfolio_links", []) or []
    link_text = "\n".join(f"[ผลงาน {i + 1}]({url})" for i, url in enumerate(links)) or "ยังไม่ได้เพิ่มลิงก์ผลงาน"
    embed.add_field(name="🔗 ผลงาน / Portfolio", value=link_text[:1024], inline=False)
    status = "🟢 กำลังหาทีม" if profile.get("looking_for_team", True) else "⚪ ยังไม่เปิดรับคำเชิญทีม"
    embed.add_field(name="📡 สถานะ", value=status, inline=True)
    embed.set_footer(text="InveNOIR Chorus Battle • เจ้าของโปรไฟล์จัดการสถานะได้เอง")
    return embed


def team_roster_text(team):
    ids = []
    owner_id = int(team.get("owner_id", 0))
    if owner_id:
        ids.append(owner_id)
    for raw_id in team.get("accepted_members", []):
        try:
            member_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if member_id and member_id not in ids:
            ids.append(member_id)
    if not ids:
        return "ยังไม่มีสมาชิกที่ยืนยันแล้ว"
    try:
        profiles = {int(p.get("user_id", 0)): p for p in team_data_load().get("profiles", [])}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        profiles = {}
    lines = []
    for member_id in ids[:12]:
        profile = profiles.get(member_id)
        if profile:
            alias = discord.utils.escape_markdown(str(profile.get("alias", "Member"))[:60])
            specialty = str(profile.get("specialties", "")).strip()
            line = f"• **{alias}** (<@{member_id}>)"
            if specialty:
                line += f" — {specialty[:90]}"
        else:
            line = f"• <@{member_id}>"
        lines.append(line)
    if len(ids) > 12:
        lines.append(f"…และสมาชิกอีก {len(ids) - 12} คน")
    return "\n".join(lines)[:1024]


def profile_text_channel(guild):
    return next((c for c in guild.text_channels if is_member_profiles(c.name)), None)


async def ensure_profile_board(guild):
    # Ensure the expected Team Finder rooms exist before posting the profile panel.
    await ensure_rooms(guild)
    channel = profile_text_channel(guild)
    if channel is None:
        raise ValueError("ไม่พบห้อง member-profiles และสร้างห้องไม่สำเร็จ")
    data = team_data_load()
    message = None
    stored_channel_id = data.get("profile_board_channel_id")
    stored_message_id = data.get("profile_board_message_id")
    if stored_channel_id and int(stored_channel_id) == channel.id and stored_message_id:
        try:
            message = await channel.fetch_message(int(stored_message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError, TypeError):
            message = None
    if message is None:
        message = await channel.send(
            content="📌 สร้างหรือแก้ไขโปรไฟล์ของคุณ แล้วเปิดสถานะหาทีมเพื่อให้ทีมต่าง ๆ ค้นหาได้",
            embed=profile_panel_embed(), view=MemberProfilePanelView(),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    else:
        await message.edit(
            content="📌 สร้างหรือแก้ไขโปรไฟล์ของคุณ แล้วเปิดสถานะหาทีมเพื่อให้ทีมต่าง ๆ ค้นหาได้",
            embed=profile_panel_embed(), view=MemberProfilePanelView(),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    data["profile_board_channel_id"] = channel.id
    data["profile_board_message_id"] = message.id
    team_data_save(data)
    return channel, message


def team_validate_fields(name, description, looking_for, availability):
    if not name or not name.strip() or len(name.strip()) > 80:
        return "ชื่อทีมต้องมี 1–80 ตัวอักษร"
    if not description or not description.strip() or len(description.strip()) > 800:
        return "คำอธิบายทีมต้องมี 1–800 ตัวอักษร"
    if not looking_for or not looking_for.strip() or len(looking_for.strip()) > 300:
        return "ตำแหน่งที่กำลังหาต้องมี 1–300 ตัวอักษร"
    if not availability or not availability.strip() or len(availability.strip()) > 200:
        return "เวลาว่างต้องมี 1–200 ตัวอักษร"
    return None


def team_embed(team):
    label, color = TEAM_STATUS_INFO.get(team.get("status", "recruiting"), TEAM_STATUS_INFO["closed"])
    name = str(team.get("team_name", "Untitled Team"))[:250]
    embed = discord.Embed(
        title=f"{label} • {name}",
        description=str(team.get("description", ""))[:4000],
        colour=discord.Colour(color),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="🔎 กำลังหาสายไหน", value=str(team.get("looking_for", "ยังไม่ระบุ"))[:1024], inline=False)
    embed.add_field(name="🗓️ เวลาที่สะดวก", value=str(team.get("availability", "ยังไม่ระบุ"))[:1024], inline=True)
    embed.add_field(name="👑 หัวหน้าทีม", value=f"<@{int(team.get('owner_id', 0))}>", inline=True)
    embed.add_field(name="👥 สมาชิกที่ยืนยันแล้ว", value=team_roster_text(team), inline=False)
    embed.add_field(name="📌 สถานะ", value=label, inline=True)
    embed.set_footer(text="InveNOIR Chorus Battle • สร้างโปรไฟล์ก่อนสมัคร หรือกด Apply to Team")
    return embed


def profile_panel_embed():
    embed = discord.Embed(
        title="INVENOIR • MEMBER PROFILE DATABASE",
        description=(
            "**สร้างโปรไฟล์ของคุณ เพื่อให้ทีมต่าง ๆ ค้นหาและชวนเข้าร่วมได้**\n\n"
            "🪪 **สร้าง / แก้ไขโปรไฟล์** — ใส่นามแฝง สายงาน ทักษะ คำแนะนำตัว และลิงก์ผลงาน\n"
            "🔎 **ดูคนที่กำลังหาทีม** — หัวหน้าทีมสามารถดูโปรไฟล์และส่งคำเชิญได้\n"
            "👤 **ดูโปรไฟล์ของฉัน** — ตรวจสอบข้อมูลและเปิด/ปิดสถานะกำลังหาทีม\n\n"
            "เมื่อทีมเชิญคุณ คุณจะได้รับ DM และเลือก **รับคำเชิญ** หรือ **ปฏิเสธ** ได้เอง\n"
            "การสมัครทีมจาก Group Finder ต้องมีโปรไฟล์และเปิดสถานะกำลังหาทีมไว้"
        ),
        colour=discord.Colour(0x9C80DD),
    )
    embed.set_footer(text="INVENOIR • MEMBER PROFILES / PORTFOLIO DIRECTORY")
    return embed


def team_panel_embed():
    embed = discord.Embed(
        title="INVENOIR • GROUP FINDER TERMINAL",
        description=(
            "**Group Finder ใช้สำหรับค้นหาสมาชิกและรวมทีมเท่านั้น**\n\n"
            "📣 **สร้างประกาศทีม** — บอกคอนเซปต์ ตำแหน่งที่กำลังหา และเวลาที่สะดวก\n"
            "🔎 **ฉันกำลังหาทีม** — ดูการ์ดทีมที่เปิดรับและส่งคำขอเข้าร่วมได้ (ต้องมีโปรไฟล์ก่อน)\n"
            "🪪 **Member Profiles** — ใส่นามแฝง ทักษะ และลิงก์ผลงาน เพื่อให้ทีมค้นหาและเชิญได้\n"
            "📋 **รายชื่อสมาชิก** — โพสต์ทีมจะแสดงหัวหน้าทีมและสมาชิกที่ยืนยันแล้ว\n\n"
            
        ),
        colour=discord.Colour(0x9C80DD),
    )
    embed.set_footer(text="CHORUS BATTLE • SQUAD FORMATION SYSTEM")
    return embed


def team_application_embed(team, application, guild):
    applicant_id = int(application["applicant_id"])
    applicant = guild.get_member(applicant_id) if guild else None
    applicant_label = f"{applicant} ({applicant.mention})" if applicant else f"สมาชิก <@{applicant_id}>"
    embed = discord.Embed(
        title="🤝 มีคำขอเข้าร่วมทีมใหม่",
        description=f"**ทีม:** {team.get('team_name', 'ทีม')}\n**ผู้สมัคร:** {applicant_label}\n\nเปิดรับสมาชิกอยู่หรือไม่ และเหมาะกับทีมของคุณไหม?",
        colour=discord.Colour(0x9C80DD),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="กำลังหา", value=str(team.get("looking_for", "ยังไม่ระบุ"))[:1024], inline=False)
    embed.add_field(name="💌 ข้อความจากผู้สมัคร", value=str(application.get("motivation", "ไม่ได้ระบุ"))[:1024], inline=False)
    embed.add_field(name="Application ID", value=f"`#{application['id']}`", inline=True)
    try:
        profile = profile_get(team_data_load(), applicant_id)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        profile = None
    if profile:
        embed.add_field(name="🪪 นามแฝง", value=str(profile.get("alias", "ยังไม่ระบุ"))[:256], inline=True)
        embed.add_field(name="🎭 สายงาน / ทักษะ", value=str(profile.get("specialties", "ยังไม่ระบุ"))[:1024], inline=False)
        embed.add_field(name="📝 แนะนำตัว / จุดเด่น", value=str(profile.get("intro", "ยังไม่ระบุ"))[:1024], inline=False)
        embed.add_field(name="🎶 แนวเพลง / เวลาที่สะดวก", value=str(profile.get("genres_availability", "ยังไม่ระบุ"))[:1024], inline=False)
        links = profile.get("portfolio_links", []) or []
        embed.add_field(name="🔗 Portfolio", value="\n".join(f"[ผลงาน {i+1}]({url})" for i, url in enumerate(links))[:1024] or "ยังไม่มีลิงก์", inline=False)
    else:
        embed.add_field(name="โปรไฟล์", value="ไม่พบโปรไฟล์ผู้สมัคร", inline=False)
    if applicant is not None:
        embed.add_field(name="Discord Account", value=f"{applicant} • ID `{applicant.id}`", inline=False)
    embed.set_footer(text="Accept เพื่อยืนยัน • Decline เพื่อปฏิเสธ")
    return embed


def full_team_application_embed(team, application, profile, member):
    applicant_id = int(application["applicant_id"])
    alias = str(application.get("alias") or (profile.get("alias", "ยังไม่ระบุ") if profile else "ยังไม่สร้างโปรไฟล์"))
    embed = discord.Embed(
        title="📨 ใบสมัครสำรอง • ทีมเต็มแล้ว",
        description=(f"**ทีม:** {team.get('team_name', application.get('team_name', 'ทีม'))}\n"
                     f"**ผู้สมัคร:** {member.mention if member else f'<@{applicant_id}>'}\n"
                     f"**นามแฝง:** {alias}\n"
                     f"**Application ID:** `#{application['id']}`"),
        colour=discord.Colour(0xD6A64F), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🎭 สายงาน / ทักษะ", value=str(application.get("position") or (profile.get("specialties", "ไม่ระบุ") if profile else "ไม่พบโปรไฟล์"))[:1024], inline=False)
    embed.add_field(name="📝 แนะนำตัว / จุดเด่น", value=str(profile.get("intro", "ไม่ระบุ") if profile else "ไม่พบโปรไฟล์")[:1024], inline=False)
    embed.add_field(name="🎶 แนวเพลง / เวลาที่สะดวก", value=str(profile.get("genres_availability", "ไม่ระบุ") if profile else "ไม่พบโปรไฟล์")[:1024], inline=False)
    embed.add_field(name="🎯 ตำแหน่งที่สมัคร", value=str(application.get("position", "ไม่ระบุ"))[:256], inline=True)
    embed.add_field(name="💌 เหตุผล / จุดเด่นที่อยากนำมาช่วยทีม", value=str(application.get("motivation", "ไม่ระบุ"))[:1024], inline=False)
    links = application.get("portfolio_links", []) or (profile.get("portfolio_links", []) if profile else []) or []
    link_text = "\n".join(f"[ผลงาน {i+1}]({url})" for i, url in enumerate(links)) or "ยังไม่มีลิงก์"
    embed.add_field(name="🔗 Portfolio", value=link_text[:1024], inline=False)
    extra = str(application.get("extra_info", "")).strip()
    if extra:
        embed.add_field(name="🗒️ ข้อมูลเพิ่มเติม", value=extra[:1024], inline=False)
    embed.set_footer(text="ข้อมูลนี้อยู่ในห้อง Staff Only • Organizer / Staff / Administrator เท่านั้น")
    return embed


async def create_full_team_application(guild, applicant, thread_id, motivation):
    if not team_is_eligible(applicant):
        return "❌ ต้องมียศสายแข่งขันก่อนส่งใบสมัครครับ"
    channel = await ensure_full_team_applications_channel(guild)
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านข้อมูลทีมไม่ได้: {str(exc)[:160]}"
        team = team_get(data, thread_id)
        if team is None:
            return "❌ ไม่พบทีมนี้ในระบบแล้ว"
        if team.get("status") != "full":
            return "🔄 สถานะทีมเปลี่ยนแล้ว กรุณาใช้ปุ่มสมัครปกติในประกาศทีม"
        if int(team.get("owner_id", 0)) == applicant.id:
            return "คุณเป็นหัวหน้าทีมนี้อยู่แล้วครับ"
        profile = profile_get(data, applicant.id)
        if profile is None:
            return "🪪 กรุณาสร้างโปรไฟล์ในห้อง `member-profiles` ก่อนส่งใบสมัคร"
        if not profile.get("looking_for_team", True):
            return "⚪ โปรไฟล์ของคุณปิดสถานะหาทีมอยู่ กรุณาเปิดสถานะก่อนสมัคร"
        active_team = member_active_team(data, applicant.id)
        if active_team is not None:
            return f"คุณอยู่ในทีม **{active_team.get('team_name', 'ทีม')}** อยู่แล้ว จึงยังส่งใบสมัครทีมสำรองไม่ได้"
        previous = next((a for a in data["full_team_applications"]
                         if int(a.get("team_thread_id", 0)) == int(thread_id)
                         and int(a.get("applicant_id", 0)) == applicant.id
                         and a.get("status") in {"pending", "waitlisted"}), None)
        if previous:
            return "คุณมีใบสมัครสำรองทีมนี้อยู่แล้ว ไม่ต้องส่งซ้ำครับ"
        app_id = max([int(a.get("id", 0)) for a in data["full_team_applications"]] + [0]) + 1
        application = {
            "id": app_id, "team_thread_id": int(thread_id), "team_name": team["team_name"],
            "team_owner_id": int(team["owner_id"]), "applicant_id": applicant.id,
            "motivation": motivation.strip(), "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "review_channel_id": channel.id, "review_message_id": None,
        }
        data["full_team_applications"].append(application)
        data["next_full_team_application_id"] = app_id + 1
        team_copy, application_copy, profile_copy = dict(team), dict(application), dict(profile)
        try:
            team_data_save(data)
        except OSError as exc:
            return f"❌ บันทึกใบสมัครไม่ได้: {str(exc)[:160]}"

    try:
        message = await channel.send(
            embed=full_team_application_embed(team_copy, application_copy, profile_copy, applicant),
            view=FullTeamApplicationReviewView(app_id),
            allowed_mentions=discord.AllowedMentions.none())
        async with TEAM_FINDER_LOCK:
            data = team_data_load()
            stored = team_get_full_application(data, app_id)
            if stored is not None:
                stored["review_message_id"] = message.id
                team_data_save(data)
    except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[InveNOIR Team Finder] Could not post full-team application #{app_id}: {exc!r}", flush=True)
        return f"⚠️ บันทึกใบสมัคร #{app_id} แล้ว แต่ส่งเข้าห้องทีมงานไม่ได้ กรุณาแจ้ง Organizer/Staff"
    return f"✅ ส่งใบสมัครสำรองทีม **{team_copy['team_name']}** แล้ว (#{app_id})\nข้อมูลของคุณถูกส่งไปยังห้องทีมงานเท่านั้น ไม่แสดงในห้องสาธารณะครับ"


async def create_registration_full_team_application(guild, applicant, team_name, alias, position, motivation, portfolio_text):
    """Accept a full-team waitlist application from #registration and forward it to staff-only review."""
    if not team_is_eligible(applicant):
        return "❌ ต้องมียศสายแข่งขันก่อนส่งใบสมัครครับ"
    team_name = str(team_name or "").strip()
    alias = str(alias or "").strip()
    position = str(position or "").strip()
    motivation = str(motivation or "").strip()
    portfolio_text = str(portfolio_text or "").strip()
    if not team_name or len(team_name) > 80:
        return "❌ กรุณากรอกชื่อทีมให้ตรงกับประกาศ (ไม่เกิน 80 ตัวอักษร)"
    if not alias or len(alias) > 60:
        return "❌ กรุณากรอกนามแฝง 1–60 ตัวอักษร"
    if not position or len(position) > 180:
        return "❌ กรุณาระบุตำแหน่งที่ต้องการสมัคร 1–180 ตัวอักษร"
    if not motivation or len(motivation) > 900:
        return "❌ กรุณาแนะนำตัว/บอกเหตุผล 1–900 ตัวอักษร"
    links, link_error = profile_parse_links(portfolio_text)
    if link_error:
        return "❌ " + link_error
    if len(links or []) > 5:
        return "❌ ใส่ลิงก์ผลงานได้สูงสุด 5 ลิงก์"

    channel = await ensure_full_team_applications_channel(guild)
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านข้อมูลทีมไม่ได้: {str(exc)[:160]}"
        normal_name = re.sub(r"\s+", " ", team_name).casefold()
        team = next((t for t in data.get("teams", [])
                     if re.sub(r"\s+", " ", str(t.get("team_name", "")).strip()).casefold() == normal_name
                     and t.get("status") == "full"), None)
        if team is None:
            return (f"❌ ไม่พบทีมชื่อ **{team_name}** ที่มีสถานะทีมเต็มในระบบ\n"
                    "กรุณาคัดลอกชื่อทีมจากประกาศใน `group-finder` ให้ตรงกัน หรือสมัครทีมที่ยังเปิดรับจากประกาศโดยตรง")
        if int(team.get("owner_id", 0)) == applicant.id:
            return "คุณเป็นหัวหน้าทีมนี้อยู่แล้วครับ"
        active_team = member_active_team(data, applicant.id)
        if active_team is not None:
            return f"คุณอยู่ในทีม **{active_team.get('team_name', 'ทีม')}** อยู่แล้ว จึงยังสมัครทีมสำรองไม่ได้"
        previous = next((a for a in data.get("full_team_applications", [])
                         if int(a.get("team_thread_id", 0)) == int(team.get("thread_id", 0))
                         and int(a.get("applicant_id", 0)) == applicant.id
                         and a.get("status") in {"pending", "waitlisted"}), None)
        if previous:
            return "คุณมีใบสมัครสำรองทีมนี้อยู่แล้ว ไม่ต้องส่งซ้ำครับ"
        app_id = max([int(a.get("id", 0)) for a in data.get("full_team_applications", [])] + [0]) + 1
        application = {
            "id": app_id,
            "team_thread_id": int(team.get("thread_id", 0)),
            "team_name": team.get("team_name", team_name),
            "team_owner_id": int(team.get("owner_id", 0)),
            "applicant_id": applicant.id,
            "alias": alias,
            "position": position,
            "motivation": motivation,
            "portfolio_links": links or [],
            "extra_info": "ส่งผ่านห้อง registration",
            "source": "registration-channel",
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "review_channel_id": channel.id,
            "review_message_id": None,
        }
        data.setdefault("full_team_applications", []).append(application)
        data["next_full_team_application_id"] = app_id + 1
        profile = profile_get(data, applicant.id)
        profile_copy = dict(profile) if profile else {
            "alias": alias, "specialties": position, "intro": "ผู้สมัครกรอกข้อมูลผ่านห้อง registration",
            "genres_availability": "ไม่ระบุ", "portfolio_links": links or []
        }
        team_copy, application_copy = dict(team), dict(application)
        team_data_save(data)

    try:
        message = await channel.send(
            content=f"📨 ใบสมัครใหม่ #{app_id} • ทีม **{team_copy['team_name']}**",
            embed=full_team_application_embed(team_copy, application_copy, profile_copy, applicant),
            view=FullTeamApplicationReviewView(app_id),
            allowed_mentions=discord.AllowedMentions.none())
        async with TEAM_FINDER_LOCK:
            latest = team_data_load()
            stored = team_get_full_application(latest, app_id)
            if stored is not None:
                stored["review_message_id"] = message.id
                team_data_save(latest)
    except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[InveNOIR Team Finder] Could not post registration application #{app_id}: {exc!r}", flush=True)
        return f"⚠️ บันทึกใบสมัคร #{app_id} แล้ว แต่ส่งเข้าห้องทีมงานไม่สำเร็จ กรุณาแจ้ง Organizer/Staff"

    try:
        await applicant.send(
            f"✅ ได้รับใบสมัครของคุณแล้ว (#{app_id})\nทีม: **{team_copy['team_name']}**\n"
            "ข้อมูลถูกส่งไปยังทีมงานในห้องส่วนตัวเพื่อพิจารณาแล้วครับ 💜",
            allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        pass
    return f"✅ ส่งใบสมัครทีม **{team_copy['team_name']}** สำเร็จแล้ว (#{app_id})\nข้อมูลถูกส่งไปยังห้องทีมงานเท่านั้นครับ 💜"


async def process_full_team_application_decision(guild, application_id, decision, actor):
    if not is_staff_or_admin(actor):
        return "❌ เฉพาะ Organizer, Staff หรือ Administrator เท่านั้นที่ดูแลใบสมัครนี้ได้"
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านใบสมัครไม่ได้: {str(exc)[:160]}"
        application = team_get_full_application(data, application_id)
        if application is None:
            return "❌ ไม่พบใบสมัครนี้"
        if application.get("status") != "pending":
            return f"ใบสมัครนี้ถูกจัดการแล้ว (สถานะ: {application.get('status')})"
        application["status"] = "waitlisted" if decision == "waitlist" else "declined"
        application["reviewed_by"] = actor.id
        application["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        app_copy = dict(application)
        team_data_save(data)
    applicant = await team_fetch_member(guild, app_copy["applicant_id"])
    if applicant is not None:
        try:
            if decision == "waitlist":
                await applicant.send(
                    f"🟡 ใบสมัครสำรองของคุณสำหรับทีม **{app_copy['team_name']}** ถูกเก็บไว้ในรายชื่อสำรองโดยทีมงานแล้ว\n"
                    "นี่ไม่ใช่การยืนยันเข้าทีม หากมีตำแหน่งว่าง ทีมงานจะพิจารณาตามความเหมาะสมครับ 💜",
                    allowed_mentions=discord.AllowedMentions.none())
            else:
                await applicant.send(
                    f"ขอบคุณที่สมัครสำรองทีม **{app_copy['team_name']}** ครับ ทีมงานปิดใบสมัครนี้แล้ว คุณยังสามารถหาทีมอื่นได้ตามปกติ 💜",
                    allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass
    return (f"🟡 เก็บใบสมัคร #{application_id} ไว้ในรายชื่อสำรองแล้ว" if decision == "waitlist"
            else f"🚫 ปิดใบสมัคร #{application_id} แล้ว")


async def team_fetch_member(guild, member_id):
    member = guild.get_member(int(member_id))
    if member is not None:
        return member
    try:
        return await guild.fetch_member(int(member_id))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def team_fetch_thread(guild, thread_id):
    thread = guild.get_thread(int(thread_id))
    if thread is None:
        try:
            channel = await guild.fetch_channel(int(thread_id))
            thread = channel if isinstance(channel, discord.Thread) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    return thread


def team_private_channel_name(team):
    raw = str(team.get("team_name", "squad")).lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", raw).strip("-")[:28] or "squad"
    unique = str(int(team.get("thread_id", 0)))[-5:] or "team"
    return f"team-{slug}-{unique}"[:95]


async def ensure_private_team_channel(guild, team):
    """Create or update one private text channel per team and add the whole confirmed roster."""
    try:
        data = team_data_load()
        live_team = team_get(data, int(team.get("thread_id", 0)))
        if live_team is None:
            live_team = dict(team)
            data["teams"].append(live_team)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None

    category = await ensure_team_rooms_category(guild)
    owner_id = int(live_team.get("owner_id", 0))
    roster_ids = [owner_id] + [int(x) for x in live_team.get("accepted_members", []) if int(x) != owner_id]
    overwrites = {guild.default_role: discord.PermissionOverwrite(
        view_channel=False, send_messages=False, read_message_history=False,
        create_public_threads=False, create_private_threads=False)}
    for role_name in ("Organizer", "Staff"):
        role = by_name(guild.roles, role_name)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False,
                send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
    for user_id in roster_ids:
        member = await team_fetch_member(guild, user_id)
        if member is not None:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=True,
                attach_files=True, embed_links=True, add_reactions=True)
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, attach_files=True, manage_messages=True)

    channel = None
    stored_id = live_team.get("team_chat_channel_id")
    if stored_id:
        channel = guild.get_channel(int(stored_id))
        if channel is None:
            try:
                fetched = await guild.fetch_channel(int(stored_id))
                channel = fetched if isinstance(fetched, discord.TextChannel) else None
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError, TypeError):
                channel = None
    topic = f"ห้องส่วนตัวของทีม {str(live_team.get('team_name', 'Team'))[:150]} • เฉพาะสมาชิกทีมและทีมงาน"
    if channel is None:
        channel = await guild.create_text_channel(
            team_private_channel_name(live_team), category=category, topic=topic,
            overwrites=overwrites, reason="InveNOIR v15 Group Finder private team conversation")
        await channel.send(
            f"🔒 **ห้องส่วนตัวของทีม {live_team.get('team_name', 'Team')}**\n"
            "ห้องนี้มองเห็นได้เฉพาะหัวหน้าทีม สมาชิกที่ยืนยันแล้ว และ Organizer/Staff สำหรับการดูแลระบบ。",
            allowed_mentions=discord.AllowedMentions.none())
    else:
        await channel.edit(name=team_private_channel_name(live_team), category=category,
                           topic=topic, overwrites=overwrites,
                           reason="InveNOIR v12.2 synchronize private team roster")
    # Reload before saving so concurrent application/invitation updates are not overwritten.
    latest_data = team_data_load()
    latest_team = team_get(latest_data, int(live_team.get("thread_id", 0)))
    if latest_team is None:
        latest_team = live_team
        latest_data["teams"].append(latest_team)
    latest_team["team_chat_channel_id"] = channel.id
    team_data_save(latest_data)
    return channel


async def team_refresh_post(guild, team):
    thread = await team_fetch_thread(guild, team["thread_id"])
    if thread is None:
        return False, "หาโพสต์ทีมใน Group Finder ไม่เจอ"
    try:
        if thread.archived:
            await thread.edit(archived=False, reason="InveNOIR Team Finder v12 update")
        message_id = int(team.get("message_id") or thread.id)
        message = await thread.fetch_message(message_id)
        await thread.edit(name=str(team["team_name"])[:100], reason="InveNOIR Team Finder v12 update")
        await message.edit(content=f"ประกาศทีม **{team['team_name']}**", embed=team_embed(team),
                           view=TeamListingView(team.get("status", "recruiting")),
                           allowed_mentions=discord.AllowedMentions.none())
        return True, thread.jump_url
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        return False, f"อัปเดตโพสต์ไม่ได้: {str(exc)[:180]}"


async def create_team_application(guild, applicant, thread_id, motivation=""):
    motivation = str(motivation or "").strip()
    if not motivation or len(motivation) > 900:
        return "❌ กรุณาเขียนข้อความแนะนำตัวเพิ่มเติม 1–900 ตัวอักษร"
    if not team_is_eligible(applicant):
        return "❌ ต้องมียศสายแข่งขันอย่างน้อยหนึ่งยศ (Vocalist, VTuber, Mixer, Aritst, Animator หรือ Team Leader) ก่อนสมัครทีม"
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านข้อมูลหาทีมไม่ได้: {str(exc)[:180]}"
        team = team_get(data, thread_id)
        if team is None:
            return "❌ ไม่พบทีมนี้ในระบบแล้ว"
        if team.get("status") != "recruiting":
            return "🔒 ทีมนี้ไม่ได้เปิดรับสมาชิกอยู่ในขณะนี้"
        if int(team.get("owner_id", 0)) == applicant.id:
            return "คุณเป็นหัวหน้าทีมนี้อยู่แล้วครับ"
        profile = profile_get(data, applicant.id)
        if profile is None:
            return "🪪 ก่อนสมัครทีม กรุณาสร้างโปรไฟล์ในห้อง `👤・member-profiles` ใส่นามแฝงและลิงก์ผลงานก่อนครับ"
        if not profile.get("looking_for_team", True):
            return "⚪ โปรไฟล์ของคุณยังไม่เปิดสถานะหาทีม กรุณาเปิดสถานะจากปุ่ม **ดูโปรไฟล์ของฉัน** ก่อนสมัคร"
        active_team = member_active_team(data, applicant.id)
        if active_team is not None:
            return f"คุณเป็นสมาชิก/หัวหน้าทีม **{active_team.get('team_name', 'ทีม')}** อยู่แล้ว จึงยังสมัครทีมใหม่ไม่ได้"
        previous = next((a for a in data["applications"]
                         if int(a.get("team_thread_id", 0)) == int(thread_id)
                         and int(a.get("applicant_id", 0)) == applicant.id
                         and a.get("status") in {"pending", "accepted"}), None)
        if previous:
            return "คุณส่งคำขอทีมนี้ไปแล้ว หรือได้รับการตอบรับแล้ว ไม่ต้องสมัครซ้ำครับ"
        app_id = max([int(a.get("id", 0)) for a in data["applications"]] + [0]) + 1
        application = {
            "id": app_id, "team_thread_id": int(thread_id), "team_name": team["team_name"],
            "team_owner_id": int(team["owner_id"]), "applicant_id": applicant.id,
            "motivation": motivation,
            "status": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data["applications"].append(application)
        data["next_application_id"] = app_id + 1
        try:
            team_data_save(data)
        except OSError as exc:
            return f"❌ บันทึกคำขอไม่ได้: {str(exc)[:180]}"
        team_copy = dict(team)
        application_copy = dict(application)

    owner = await team_fetch_member(guild, team_copy["owner_id"])
    if owner is None:
        return f"⚠️ บันทึกคำขอ #{app_id} แล้ว แต่หาหัวหน้าทีมไม่พบ กรุณาแจ้งทีมงาน"
    try:
        await owner.send(embed=team_application_embed(team_copy, application_copy, guild),
                         view=TeamApplicationDecisionView(app_id),
                         allowed_mentions=discord.AllowedMentions.none())
        return f"✅ ส่งคำขอเข้าทีม **{team_copy['team_name']}** แล้ว! หัวหน้าทีมจะได้รับข้อความส่วนตัวเพื่อพิจารณา (คำขอ #{app_id})"
    except (discord.Forbidden, discord.HTTPException):
        return (f"✅ บันทึกคำขอเข้าทีม **{team_copy['team_name']}** แล้ว (#{app_id}) แต่ส่ง DM ให้หัวหน้าทีมไม่ได้\n"
                "หัวหน้าทีมสามารถใช้ `/team_applications` เพื่อดูคำขอและ `/team_application_decide` เพื่อตอบรับหรือปฏิเสธได้")


async def create_private_team_coordination(guild, team, application):
    """Add all confirmed roster members to one private channel shared by the whole team."""
    applicant_id = int(application["applicant_id"])
    try:
        channel = await ensure_private_team_channel(guild, team)
    except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[InveNOIR Team Finder] Could not create private team room: {exc!r}", flush=True)
        channel = None
    if channel is None:
        owner = await team_fetch_member(guild, team["owner_id"])
        applicant = await team_fetch_member(guild, applicant_id)
        if owner is not None:
            try:
                await owner.send(f"⚠️ รับสมาชิกใหม่เข้า **{team['team_name']}** แล้ว แต่สร้างห้องทีมส่วนตัวไม่สำเร็จ กรุณาแจ้ง Organizer/Staff")
            except (discord.Forbidden, discord.HTTPException):
                pass
        if applicant is not None:
            try:
                await applicant.send(f"⚠️ คุณได้รับเข้าทีม **{team['team_name']}** แล้ว แต่ระบบสร้างห้องทีมส่วนตัวไม่สำเร็จ กรุณาติดต่อหัวหน้าทีมหรือทีมงาน")
            except (discord.Forbidden, discord.HTTPException):
                pass
        return None
    applicant = await team_fetch_member(guild, applicant_id)
    try:
        await channel.send(
            f"🤝 **อัปเดตสมาชิกทีม {team['team_name']}**\nสมาชิกที่เพิ่งได้รับการตอบรับ: {applicant.mention if applicant else f'<@{applicant_id}>'}\n"
            "ทุกคนในรายชื่อทีมที่ยืนยันแล้วจะใช้ห้องส่วนตัวเดียวกันนี้ร่วมกันได้ครับ 💜",
            allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        pass
    owner = await team_fetch_member(guild, team["owner_id"])
    if owner is not None:
        try:
            await owner.send(
                f"✅ รับสมาชิกใหม่เข้า **{team['team_name']}** แล้ว\nห้องคุยส่วนตัวของทีม (ใช้ร่วมกันทั้งทีม): {channel.jump_url}",
                allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass
    return channel.jump_url


async def process_team_application_decision(guild, application_id, decision, actor_id, allow_staff=False):
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านข้อมูลคำขอไม่ได้: {str(exc)[:180]}"
        application = team_get_application(data, application_id)
        if application is None:
            return "❌ ไม่พบคำขอนี้"
        if application.get("status") != "pending":
            return f"คำขอนี้ถูกจัดการไปแล้ว (สถานะ: {application.get('status')})"
        team = team_get(data, application["team_thread_id"])
        if team is None:
            application["status"] = "cancelled"
            team_data_save(data)
            return "❌ ไม่พบทีมเดิม คำขอนี้ถูกยกเลิก"
        actor_is_owner = int(application["team_owner_id"]) == int(actor_id)
        actor_is_staff = False
        if allow_staff:
            actor = guild.get_member(int(actor_id))
            actor_is_staff = actor is not None and team_can_manage(actor, team, allow_staff=True)
        if not actor_is_owner and not actor_is_staff:
            return "❌ เฉพาะหัวหน้าทีมหรือทีมงานที่ได้รับอนุญาตเท่านั้นที่จัดการคำขอนี้ได้"
        if decision == "accept" and team.get("status") != "recruiting":
            return "🔒 ทีมไม่ได้เปิดรับสมาชิกแล้ว กรุณาเปิดรับอีกครั้งก่อนตอบรับคำขอ"
        applicant_id = int(application["applicant_id"])
        if decision == "accept":
            active_team = member_active_team(data, applicant_id, exclude_thread_id=int(application["team_thread_id"]))
            if active_team is not None:
                return f"❌ สมาชิกคนนี้อยู่ในทีม **{active_team.get('team_name', 'ทีม')}** แล้ว จึงยังรับเข้าทีมซ้ำไม่ได้"
        application["status"] = "accepted" if decision == "accept" else "declined"
        application["decided_at"] = datetime.now(timezone.utc).isoformat()
        if decision == "accept":
            accepted = team.setdefault("accepted_members", [])
            if applicant_id not in accepted:
                accepted.append(applicant_id)
            profile = profile_get(data, applicant_id)
            if profile is not None:
                profile["looking_for_team"] = False
                profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            for other_app in data.get("applications", []):
                if (int(other_app.get("applicant_id", 0)) == applicant_id
                        and other_app.get("status") == "pending"
                        and int(other_app.get("team_thread_id", 0)) != int(application["team_thread_id"])):
                    other_app["status"] = "cancelled"
                    other_app["decided_at"] = datetime.now(timezone.utc).isoformat()
            for other_invite in data.get("invitations", []):
                if (int(other_invite.get("applicant_id", 0)) == applicant_id
                        and other_invite.get("status") == "pending"
                        and int(other_invite.get("id", 0)) != int(application_id)):
                    other_invite["status"] = "cancelled"
                    other_invite["decided_at"] = datetime.now(timezone.utc).isoformat()
        team_copy, application_copy = dict(team), dict(application)
        team_data_save(data)

    applicant = await team_fetch_member(guild, application_copy["applicant_id"])
    if decision == "decline":
        if applicant:
            try:
                await applicant.send(f"ขอบคุณที่สนใจทีม **{team_copy['team_name']}** ครับ แต่ครั้งนี้หัวหน้าทีมยังไม่ได้รับคำขอของคุณ ขอให้เจอทีมที่เหมาะสมเร็ว ๆ นะครับ 💜")
            except (discord.Forbidden, discord.HTTPException):
                pass
        return f"🚫 ปฏิเสธคำขอ #{application_id} สำหรับทีม **{team_copy['team_name']}** แล้ว"

    await team_refresh_post(guild, team_copy)  # Update the public roster after acceptance.
    thread_url = await create_private_team_coordination(guild, team_copy, application_copy)
    if applicant:
        try:
            extra = f"\nห้องคุยส่วนตัวของทีม: {thread_url}" if thread_url else "\nหากไม่ได้รับ DM ให้ติดต่อหัวหน้าทีมในเซิร์ฟเวอร์"
            await applicant.send(f"🎉 คำขอของคุณได้รับการตอบรับจากทีม **{team_copy['team_name']}** แล้ว!{extra}",
                                 allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass
    return f"✅ ตอบรับคำขอ #{application_id} เข้าทีม **{team_copy['team_name']}** แล้ว" + (f"\nสร้างห้องคุยส่วนตัวแล้ว: {thread_url}" if thread_url else "\nส่งข้อความแจ้งสมาชิกแล้ว หาก DM ปิดอยู่ให้ติดต่อกันผ่านเซิร์ฟเวอร์")


def register_team_finder_views(bot):
    # Persistent static controls survive bot restarts.
    bot.add_view(TeamFinderPanelView())
    bot.add_view(TeamListingView())
    bot.add_view(MemberProfilePanelView())
    bot.add_view(ProfileManageView())
    try:
        data = team_data_load()
        for app in data.get("applications", []):
            if app.get("status") == "pending":
                bot.add_view(TeamApplicationDecisionView(int(app["id"])))
        for invitation in data.get("invitations", []):
            if invitation.get("status") == "pending":
                bot.add_view(TeamInvitationView(int(invitation["id"])))
        for app in data.get("full_team_applications", []):
            if app.get("status") == "pending":
                bot.add_view(FullTeamApplicationReviewView(int(app["id"])))  # legacy waitlist applications
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[InveNOIR Team Finder] Could not restore pending application/invitation views: {exc!r}", flush=True)


class TeamCreateModal(discord.ui.Modal, title="สร้างประกาศหาทีม • Group Finder"):
    team_name = discord.ui.TextInput(label="ชื่อทีม", placeholder="เช่น TEAM ECLIPSE", max_length=80)
    description = discord.ui.TextInput(label="คอนเซปต์ / แนะนำทีม", style=discord.TextStyle.paragraph,
                                       placeholder="ทีมของคุณเป็นแนวไหน?", max_length=800)
    looking_for = discord.ui.TextInput(label="กำลังหาสายไหน", style=discord.TextStyle.paragraph,
                                       placeholder="เช่น Mixer ×1, Animator ×1", max_length=300)
    availability = discord.ui.TextInput(label="เวลาที่สะดวกทำงาน", placeholder="เช่น เสาร์–อาทิตย์ช่วงเย็น", max_length=200)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID or not team_is_eligible(interaction.user):
            return await interaction.response.send_message("❌ ต้องเป็นสมาชิกสายแข่งขันก่อนสร้างประกาศใน Group Finder", ephemeral=True)
        values = [str(self.team_name.value).strip(), str(self.description.value).strip(),
                  str(self.looking_for.value).strip(), str(self.availability.value).strip()]
        invalid = team_validate_fields(*values)
        if invalid:
            return await interaction.response.send_message("❌ " + invalid, ephemeral=True)
        forum = team_finder_forum(interaction.guild)
        if forum is None:
            return await interaction.response.send_message("❌ ไม่พบห้อง `group-finder` ที่เป็น Forum หรือ Text Channel กรุณาให้ทีมงานตรวจสอบห้อง", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with TEAM_FINDER_LOCK:
            try:
                data = team_data_load()
                existing = next((t for t in data["teams"] if int(t.get("owner_id", 0)) == interaction.user.id
                                 and t.get("status") in TEAM_ACTIVE_STATUSES), None)
                if existing:
                    return await interaction.followup.send(
                        f"คุณมีทีมที่ยังเปิดใช้งานอยู่แล้ว: **{existing['team_name']}** (สถานะ {team_status_text(existing['status'])})\n"
                        "ให้แก้โพสต์เดิมหรือปิดประกาศเดิมก่อนลงทีมใหม่ครับ", ephemeral=True)
                team = {
                    "team_name": values[0], "description": values[1], "looking_for": values[2],
                    "availability": values[3], "owner_id": interaction.user.id,
                    "status": "recruiting", "accepted_members": [],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "thread_id": 0, "message_id": 0, "team_chat_channel_id": None,
                }
                thread, message = await create_team_finder_thread(
                    forum,
                    name=values[0][:100],
                    content=f"ประกาศทีม **{values[0]}**",
                    embeds=[team_embed(team)],
                    view=TeamListingView("recruiting"),
                    reason="InveNOIR Team Finder registration",
                )
                team["thread_id"] = thread.id
                team["message_id"] = message.id
                data["teams"].append(team)
                team_data_save(data)
            except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                traceback.print_exc()
                return await interaction.followup.send(
                    f"❌ สร้างประกาศ Group Finder ไม่สำเร็จ: {type(exc).__name__}: {str(exc)[:220]}\n"
                    "ตรวจสิทธิ์บอทใน group-finder: View Channel, Send Messages, Embed Links, Create Posts (Forum) หรือ Create Public Threads (Text Channel) และ Send Messages in Threads",
                    ephemeral=True)
        await interaction.followup.send(
            f"✅ สร้างประกาศหา/รับสมาชิกสำหรับทีม **{values[0]}** แล้ว!\nสถานะเริ่มต้น: 🟢 กำลังรับสมาชิก\nโพสต์ทีม: {thread.jump_url}\n\n"
            "โพสต์นี้ใช้สำหรับ Group Finder เท่านั้น ยังไม่ใช่ใบสมัครแข่งขัน เมื่อทีมครบแล้วให้ส่งใบสมัครในห้อง `📝・registration`",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class TeamEditModal(discord.ui.Modal, title="แก้ไขข้อมูลทีม"):
    def __init__(self, team):
        super().__init__(timeout=300)
        self.thread_id = int(team["thread_id"])
        self.team_name = discord.ui.TextInput(label="ชื่อทีม", default=str(team["team_name"])[:80], max_length=80)
        self.description = discord.ui.TextInput(label="คอนเซปต์ / แนะนำทีม", style=discord.TextStyle.paragraph,
                                                default=str(team["description"])[:800], max_length=800)
        self.looking_for = discord.ui.TextInput(label="กำลังหาสายไหน", style=discord.TextStyle.paragraph,
                                                default=str(team["looking_for"])[:300], max_length=300)
        self.availability = discord.ui.TextInput(label="เวลาที่สะดวกทำงาน", default=str(team["availability"])[:200], max_length=200)
        for item in (self.team_name, self.description, self.looking_for, self.availability):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID:
            return await interaction.response.send_message("ใช้ได้เฉพาะในเซิร์ฟเวอร์ InveNOIR", ephemeral=True)
        values = [str(self.team_name.value).strip(), str(self.description.value).strip(),
                  str(self.looking_for.value).strip(), str(self.availability.value).strip()]
        invalid = team_validate_fields(*values)
        if invalid:
            return await interaction.response.send_message("❌ " + invalid, ephemeral=True)
        async with TEAM_FINDER_LOCK:
            try:
                data = team_data_load()
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return await interaction.response.send_message(f"❌ อ่านข้อมูลทีมไม่ได้: {str(exc)[:160]}", ephemeral=True)
            team = team_get(data, self.thread_id)
            if team is None:
                return await interaction.response.send_message("❌ ไม่พบข้อมูลทีมนี้", ephemeral=True)
            if not team_can_manage(interaction.user, team):
                return await interaction.response.send_message("❌ เฉพาะหัวหน้าทีมหรือทีมงานที่ได้รับอนุญาตแก้ไขได้", ephemeral=True)
            team.update({"team_name": values[0], "description": values[1],
                         "looking_for": values[2], "availability": values[3]})
            team_copy = dict(team)
            team_data_save(data)
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, detail = await team_refresh_post(interaction.guild, team_copy)
        await interaction.followup.send(("✅ อัปเดตข้อมูลทีมแล้ว: " if ok else "⚠️ บันทึกข้อมูลแล้ว แต่ ") + detail, ephemeral=True)


class TeamListingView(discord.ui.View):
    def __init__(self, status="recruiting"):
        super().__init__(timeout=None)
        apply_label = "🤝 สมัครเข้าทีม" if status == "recruiting" else ("🔴 ทีมเต็มแล้ว" if status == "full" else "🔒 ปิดรับสมัคร")
        apply_style = discord.ButtonStyle.success if status == "recruiting" else discord.ButtonStyle.secondary
        apply_btn = discord.ui.Button(label=apply_label, style=apply_style,
                                      custom_id="invenoir:team:apply", disabled=status in {"full", "closed"})
        apply_btn.callback = self.apply_callback
        self.add_item(apply_btn)
        toggle_label = "🔓 เปิดรับสมาชิกอีกครั้ง" if status == "full" else "🔒 ทำเครื่องหมายว่าทีมเต็ม" if status == "recruiting" else "ปิดรับสมัครแล้ว"
        toggle_btn = discord.ui.Button(label=toggle_label, style=discord.ButtonStyle.secondary,
                                       custom_id="invenoir:team:toggle", disabled=status == "closed")
        toggle_btn.callback = self.toggle_callback
        self.add_item(toggle_btn)
        edit_btn = discord.ui.Button(label="✏️ แก้ไขข้อมูลทีม", style=discord.ButtonStyle.primary,
                                     custom_id="invenoir:team:edit", disabled=status == "closed")
        edit_btn.callback = self.edit_callback
        self.add_item(edit_btn)
        close_btn = discord.ui.Button(label="⏹️ ปิดประกาศ", style=discord.ButtonStyle.danger,
                                      custom_id="invenoir:team:close", disabled=status == "closed")
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    async def _get_team(self, interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("ใช้ปุ่มนี้จากโพสต์ทีมใน group-finder เท่านั้น", ephemeral=True)
            return None, None
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            await interaction.response.send_message("❌ อ่านข้อมูลทีมไม่ได้ กรุณาแจ้งทีมงาน", ephemeral=True)
            return None, None
        team = team_get(data, interaction.channel.id)
        if team is None:
            await interaction.response.send_message("❌ โพสต์นี้ไม่ได้ลงทะเบียนผ่านระบบ Team Finder หรือข้อมูลหายไปแล้ว", ephemeral=True)
            return None, None
        return data, team

    async def apply_callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.Thread):
            return await interaction.response.send_message("ใช้ได้จากโพสต์ทีมใน Group Finder เท่านั้น", ephemeral=True)
        try:
            data = team_data_load()
            team = team_get(data, interaction.channel.id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            team = None
        if team is None:
            return await interaction.response.send_message("❌ ไม่พบข้อมูลทีมนี้", ephemeral=True)
        if team.get("status") == "full":
            return await interaction.response.send_message(
                "🔴 ทีมนี้เต็มแล้วครับ Group Finder ใช้สำหรับหาสมาชิกเท่านั้น ส่วนการสมัครแข่งขันอย่างเป็นทางการให้หัวหน้าทีมส่งใบสมัครเมื่อรวมทีมครบแล้ว",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        if team.get("status") != "recruiting":
            return await interaction.response.send_message("🔒 ทีมนี้ปิดรับสมัครแล้วครับ", ephemeral=True)
        await interaction.response.send_modal(TeamApplyModal(interaction.channel.id))

    async def toggle_callback(self, interaction: discord.Interaction):
        data, team = await self._get_team(interaction)
        if team is None:
            return
        if not team_can_manage(interaction.user, team):
            return await interaction.response.send_message("❌ เฉพาะหัวหน้าทีมหรือทีมงานเท่านั้น", ephemeral=True)
        async with TEAM_FINDER_LOCK:
            try:
                data = team_data_load()
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return await interaction.response.send_message(f"❌ อ่านข้อมูลทีมไม่ได้: {str(exc)[:160]}", ephemeral=True)
            team = team_get(data, interaction.channel.id)
            if team is None:
                return await interaction.response.send_message("❌ ไม่พบข้อมูลทีม", ephemeral=True)
            if team.get("status") == "closed":
                return await interaction.response.send_message("ทีมนี้ปิดประกาศแล้ว หากต้องการกลับมารับสมาชิก ให้สร้างประกาศทีมใหม่ครับ", ephemeral=True)
            team["status"] = "full" if team.get("status") == "recruiting" else "recruiting"
            team_copy = dict(team)
            team_data_save(data)
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, detail = await team_refresh_post(interaction.guild, team_copy)
        if ok:
            await interaction.followup.send(f"✅ เปลี่ยนสถานะทีมเป็น **{team_status_text(team_copy['status'])}** แล้ว", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ บันทึกสถานะแล้ว แต่แก้โพสต์ไม่สำเร็จ: {detail}", ephemeral=True)

    async def edit_callback(self, interaction: discord.Interaction):
        data, team = await self._get_team(interaction)
        if team is None:
            return
        if not team_can_manage(interaction.user, team):
            return await interaction.response.send_message("❌ เฉพาะหัวหน้าทีมหรือทีมงานเท่านั้น", ephemeral=True)
        await interaction.response.send_modal(TeamEditModal(team))

    async def close_callback(self, interaction: discord.Interaction):
        data, team = await self._get_team(interaction)
        if team is None:
            return
        if not team_can_manage(interaction.user, team):
            return await interaction.response.send_message("❌ เฉพาะหัวหน้าทีมหรือทีมงานเท่านั้น", ephemeral=True)
        async with TEAM_FINDER_LOCK:
            try:
                data = team_data_load()
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return await interaction.response.send_message(f"❌ อ่านข้อมูลทีมไม่ได้: {str(exc)[:160]}", ephemeral=True)
            team = team_get(data, interaction.channel.id)
            if team is None:
                return await interaction.response.send_message("❌ ไม่พบข้อมูลทีม", ephemeral=True)
            team["status"] = "closed"
            team_copy = dict(team)
            team_data_save(data)
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, detail = await team_refresh_post(interaction.guild, team_copy)
        await interaction.followup.send("⏹️ ปิดประกาศทีมแล้ว; คำขอใหม่จะถูกปิดกั้น" if ok else f"⚠️ บันทึกแล้ว แต่แก้โพสต์ไม่ได้: {detail}", ephemeral=True)


class FullTeamWaitlistModal(discord.ui.Modal, title="สมัครสำรองทีมที่เต็มแล้ว"):
    motivation = discord.ui.TextInput(
        label="ทำไมถึงอยากเข้าทีมนี้?", style=discord.TextStyle.paragraph,
        placeholder="บอกเหตุผล จุดเด่น หรือสิ่งที่คุณช่วยทีมได้", max_length=700, min_length=10)

    def __init__(self, team_thread_id):
        super().__init__(timeout=300)
        self.team_thread_id = int(team_thread_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID:
            return await interaction.response.send_message("ใช้ได้เฉพาะใน InveNOIR Chorus Battle", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await create_full_team_application(
            interaction.guild, interaction.user, self.team_thread_id, str(self.motivation.value))
        await interaction.followup.send(result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class FullTeamApplicationReviewView(discord.ui.View):
    def __init__(self, application_id, disabled=False):
        super().__init__(timeout=None)
        self.application_id = int(application_id)
        wait_btn = discord.ui.Button(label="🟡 รับไว้ในรายชื่อสำรอง", style=discord.ButtonStyle.success,
                                     custom_id=f"invenoir:fullteam:waitlist:{self.application_id}", disabled=disabled)
        wait_btn.callback = self.waitlist_callback
        self.add_item(wait_btn)
        decline_btn = discord.ui.Button(label="❌ ปิดใบสมัคร", style=discord.ButtonStyle.danger,
                                        custom_id=f"invenoir:fullteam:decline:{self.application_id}", disabled=disabled)
        decline_btn.callback = self.decline_callback
        self.add_item(decline_btn)

    async def _decide(self, interaction, decision):
        if not interaction.guild or interaction.guild.id != GUILD_ID or not is_staff_or_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ เฉพาะ Organizer, Staff หรือ Administrator เท่านั้นที่จัดการใบสมัครนี้ได้", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await process_full_team_application_decision(
            interaction.guild, self.application_id, decision, interaction.user)
        try:
            data = team_data_load()
            app = team_get_full_application(data, self.application_id)
            if interaction.message and app and app.get("status") != "pending":
                await interaction.message.edit(view=FullTeamApplicationReviewView(self.application_id, disabled=True))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, discord.HTTPException, discord.Forbidden):
            pass
        await interaction.followup.send(result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def waitlist_callback(self, interaction: discord.Interaction):
        await self._decide(interaction, "waitlist")

    async def decline_callback(self, interaction: discord.Interaction):
        await self._decide(interaction, "decline")


class TeamApplyModal(discord.ui.Modal, title="สมัครเข้าร่วมทีม"):
    motivation = discord.ui.TextInput(
        label="ข้อความแนะนำตัวถึงหัวหน้าทีม",
        placeholder="บอกว่าคุณอยากช่วยทีมอย่างไร และมีอะไรอยากให้ทีมรู้",
        style=discord.TextStyle.paragraph, min_length=1, max_length=900,
    )

    def __init__(self, thread_id):
        super().__init__(timeout=300)
        self.thread_id = int(thread_id)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await create_team_application(
            interaction.guild, interaction.user, self.thread_id, str(self.motivation.value))
        await interaction.followup.send(result, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())


class TeamBrowseView(discord.ui.View):
    """Large, paginated team cards; no dropdown/select menu."""
    def __init__(self, teams, owner_id=None, index=0):
        super().__init__(timeout=300)
        self.teams = [dict(t) for t in teams]
        self.owner_id = int(owner_id) if owner_id else None
        self.index = max(0, min(int(index), max(0, len(self.teams) - 1)))
        self.prev_btn = discord.ui.Button(label="◀ ก่อนหน้า", style=discord.ButtonStyle.secondary,
                                          disabled=self.index <= 0)
        self.prev_btn.callback = self.previous_callback
        self.add_item(self.prev_btn)
        self.next_btn = discord.ui.Button(label="ถัดไป ▶", style=discord.ButtonStyle.secondary,
                                          disabled=self.index >= len(self.teams) - 1)
        self.next_btn.callback = self.next_callback
        self.add_item(self.next_btn)
        self.apply_btn = discord.ui.Button(label="🤝 สมัครทีมนี้", style=discord.ButtonStyle.success,
                                           disabled=not self.teams)
        self.apply_btn.callback = self.apply_callback
        self.add_item(self.apply_btn)
        close_btn = discord.ui.Button(label="✖ ปิด", style=discord.ButtonStyle.danger)
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    def current_team(self):
        return self.teams[self.index] if self.teams else None

    def current_embed(self):
        team = self.current_team()
        if team is None:
            return discord.Embed(title="ยังไม่มีทีมเปิดรับสมาชิก", colour=discord.Colour(0x858B98))
        embed = team_embed(team)
        embed.description = (str(team.get("description", ""))[:3000] +
                             f"\n\n**ทีมที่ {self.index + 1} จาก {len(self.teams)}**\n"
                             "ใช้ปุ่มก่อนหน้า/ถัดไปเพื่อดูทีมอื่น โดยไม่ต้องเลือกจาก Dropdown")
        embed.set_footer(text="INVENOIR • TEAM CARDS / PAGINATED BROWSER")
        return embed

    async def _check_owner(self, interaction):
        if self.owner_id is not None and interaction.user.id != self.owner_id:
            await interaction.response.send_message("แผงค้นหานี้เป็นของผู้ที่เปิดใช้งาน กรุณากดปุ่มค้นหาทีมของคุณเอง", ephemeral=True)
            return False
        return True

    async def _move(self, interaction, delta):
        if not await self._check_owner(interaction):
            return
        self.index = max(0, min(self.index + delta, len(self.teams) - 1))
        self.prev_btn.disabled = self.index <= 0
        self.next_btn.disabled = self.index >= len(self.teams) - 1
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    async def previous_callback(self, interaction):
        await self._move(interaction, -1)

    async def next_callback(self, interaction):
        await self._move(interaction, 1)

    async def apply_callback(self, interaction):
        if not await self._check_owner(interaction):
            return
        team = self.current_team()
        if team is None:
            return await interaction.response.send_message("ไม่พบทีมที่เลือก", ephemeral=True)
        await interaction.response.send_modal(TeamApplyModal(int(team["thread_id"])))

    async def close_callback(self, interaction):
        if not await self._check_owner(interaction):
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="ปิดหน้าต่างค้นหาทีมแล้ว", embed=None, view=self)


def registration_parse_discord_id(raw):
    """Accept a raw Discord snowflake or a pasted <@mention>."""
    value = str(raw or "").strip()
    match = re.fullmatch(r"(?:<@!?(\d{15,22})>|(\d{15,22}))", value)
    return int(match.group(1) or match.group(2)) if match else None


def registration_parse_roster(raw):
    """Parse one member per line: Discord ID | alias | position."""
    lines = [line.strip() for line in str(raw or "").splitlines() if line.strip()]
    if not lines:
        return None, "กรุณาใส่รายชื่อสมาชิกอย่างน้อย 1 คน"
    if len(lines) > 20:
        return None, "ทีมหนึ่งทีมใส่สมาชิกได้สูงสุด 20 คนในระบบนี้"
    roster, seen = [], set()
    for number, line in enumerate(lines, start=1):
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) != 3:
            return None, f"บรรทัดที่ {number} รูปแบบไม่ถูกต้อง ใช้ `Discord ID | ชื่อในทีม | ตำแหน่ง`"
        user_id = registration_parse_discord_id(parts[0])
        alias, position = parts[1], parts[2]
        if user_id is None:
            return None, f"Discord ID ในบรรทัดที่ {number} ไม่ถูกต้อง (ใส่ตัวเลข ID หรือ @mention)"
        if user_id in seen:
            return None, f"พบ Discord ID ซ้ำในบรรทัดที่ {number}"
        if not alias or len(alias) > 60:
            return None, f"ชื่อในทีมของบรรทัดที่ {number} ต้องมี 1–60 ตัวอักษร"
        if not position or len(position) > 100:
            return None, f"ตำแหน่งของบรรทัดที่ {number} ต้องมี 1–100 ตัวอักษร"
        seen.add(user_id)
        roster.append({"user_id": user_id, "alias": alias, "position": position, "portfolio_links": []})
    return roster, None


def registration_parse_portfolios(raw, roster):
    """Parse optional per-member links: Discord ID | https://portfolio.example"""
    lines = [line.strip() for line in str(raw or "").splitlines() if line.strip()]
    roster_ids = {int(person["user_id"]) for person in roster}
    links_by_user = {user_id: [] for user_id in roster_ids}
    if len(lines) > 50:
        return None, "ใส่ลิงก์ผลงานได้สูงสุด 50 บรรทัด"
    for number, line in enumerate(lines, start=1):
        parts = [part.strip() for part in line.split("|", 1)]
        if len(parts) != 2:
            return None, f"ลิงก์ผลงานบรรทัดที่ {number} ต้องใช้ `Discord ID | URL`"
        user_id = registration_parse_discord_id(parts[0])
        url = parts[1]
        if user_id is None or user_id not in roster_ids:
            return None, f"Discord ID ในลิงก์ผลงานบรรทัดที่ {number} ไม่อยู่ในรายชื่อสมาชิกทีม"
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None, f"URL ในบรรทัดที่ {number} ไม่ถูกต้อง ต้องขึ้นต้นด้วย https:// หรือ http://"
        if len(url) > 300:
            return None, f"URL ในบรรทัดที่ {number} ยาวเกินไป (สูงสุด 300 ตัวอักษร)"
        if url not in links_by_user[user_id]:
            links_by_user[user_id].append(url)
        if len(links_by_user[user_id]) > 5:
            return None, f"สมาชิกแต่ละคนใส่ผลงานได้สูงสุด 5 ลิงก์ (ID {user_id})"
    for person in roster:
        person["portfolio_links"] = links_by_user[int(person["user_id"])]
    return roster, None


def team_registration_get(data, registration_id):
    return next((item for item in data.get("competition_registrations", [])
                 if int(item.get("id", 0)) == int(registration_id)), None)


def team_registration_status_text(status):
    return {
        "pending": "🟡 รอทีมงานตรวจสอบ",
        "approved": "🟢 ยืนยันสมัครแข่งขันแล้ว",
        "declined": "🔴 ใบสมัครไม่ผ่านการพิจารณา",
        "processing": "🟠 กำลังดำเนินการ",
        "channel_error": "🟠 ส่งใบสมัครแล้ว แต่ต้องให้ทีมงานซ่อมห้องทีม",
    }.get(status, str(status or "ไม่ทราบสถานะ"))


def team_registration_embed(registration):
    team_name = discord.utils.escape_markdown(str(registration.get("team_name", "Team"))[:80])
    leader_id = int(registration.get("leader_id", 0))
    embed = discord.Embed(
        title=f"📝 ใบสมัครเข้าแข่งขัน #{registration.get('id')} • {team_name}",
        description=(f"**หัวหน้าทีม:** <@{leader_id}> (`{leader_id}`)\n"
                     f"**ผู้ส่งใบสมัคร:** <@{int(registration.get('submitted_by', leader_id))}>\n"
                     f"**สถานะ:** {team_registration_status_text(registration.get('status'))}\n"
                     f"**ห้องทีม:** <#{int(registration.get('team_channel_id') or 0)}>" if registration.get("team_channel_id") else
                     f"**หัวหน้าทีม:** <@{leader_id}> (`{leader_id}`)\n"
                     f"**ผู้ส่งใบสมัคร:** <@{int(registration.get('submitted_by', leader_id))}>\n"
                     f"**สถานะ:** {team_registration_status_text(registration.get('status'))}\n"
                     "**ห้องทีม:** ยังสร้างไม่สำเร็จ — ใช้ /team_registration_sync"),
        colour=discord.Colour(0x9C80DD),
        timestamp=datetime.now(timezone.utc),
    )
    roster_lines = []
    portfolio_lines = []
    for person in registration.get("roster", [])[:20]:
        uid = int(person.get("user_id", 0))
        alias = discord.utils.escape_markdown(str(person.get("alias", "Member"))[:30])
        position = discord.utils.escape_markdown(str(person.get("position", "ไม่ระบุ"))[:40])
        roster_lines.append(f"• <@{uid}> — **{alias}** / {position} (`{uid}`)")
        for url in person.get("portfolio_links", [])[:5]:
            portfolio_lines.append(f"• <@{uid}> — {url}")
    def add_chunked_fields(title, lines, limit=900):
        chunks, current = [], ""
        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > limit and current:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        if not chunks:
            chunks = ["ยังไม่มีข้อมูล"]
        for index, chunk in enumerate(chunks[:4], start=1):
            field_title = title if len(chunks) == 1 else f"{title} ({index}/{min(len(chunks), 4)})"
            embed.add_field(name=field_title[:256], value=chunk[:1024], inline=False)
        if len(chunks) > 4:
            embed.add_field(name=f"{title} (เพิ่มเติม)", value="มีข้อมูลเพิ่มเติมที่บันทึกไว้ในระบบแล้ว", inline=False)
    add_chunked_fields(f"👥 รายชื่อสมาชิก ({len(registration.get('roster', []))})", roster_lines)
    embed.add_field(name="🧭 คอนเซปต์ / แนะนำทีม", value=str(registration.get("introduction", "ไม่ระบุ"))[:1024], inline=False)
    add_chunked_fields("🔗 ผลงานสมาชิก", portfolio_lines[:5])
    if len(portfolio_lines) > 5:
        embed.add_field(name="ผลงานเพิ่มเติม", value=f"ยังมีลิงก์ผลงานอีก {len(portfolio_lines) - 5} ลิงก์ที่บันทึกไว้ในระบบ", inline=False)
    embed.set_footer(text="INVENOIR • OFFICIAL TEAM REGISTRATION • ข้อมูลนี้เป็นส่วนตัวสำหรับทีมงาน")
    return embed


async def team_registration_review_channel(guild):
    return await ensure_team_registration_review_channel(guild)


async def ensure_registered_team_channel(guild, registration):
    """Create/update the private chat for the exact roster submitted in Team Registration."""
    category = await ensure_registered_teams_category(guild)
    roster = registration.get("roster", [])
    overwrites = {guild.default_role: discord.PermissionOverwrite(
        view_channel=False, send_messages=False, read_message_history=False,
        create_public_threads=False, create_private_threads=False)}
    for role_name in ("Organizer", "Staff", "Admin", "Administrator"):
        role = by_name(guild.roles, role_name)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False,
                send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
    for person in roster:
        member = await team_fetch_member(guild, int(person["user_id"]))
        if member is None or member.bot:
            raise ValueError(f"ไม่พบสมาชิก Discord ID {person.get('user_id')} ในเซิร์ฟเวอร์ หรือบัญชีนี้เป็นบอท")
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            attach_files=True, embed_links=True, add_reactions=True,
            send_messages_in_threads=True, create_public_threads=False, create_private_threads=False)
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, attach_files=True, manage_channels=True, manage_messages=True)
    reg_id = int(registration["id"])
    raw_name = str(registration.get("team_name", "team")).lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", raw_name).strip("-")[:35] or "team"
    channel_name = f"registered-{reg_id:04d}-{slug}"[:95]
    channel = None
    stored_id = registration.get("team_channel_id")
    if not stored_id:
        channel = next((candidate for candidate in guild.text_channels
                        if candidate.name == channel_name and candidate.category_id == category.id), None)
    if stored_id:
        channel = guild.get_channel(int(stored_id))
        if channel is None:
            try:
                fetched = await guild.fetch_channel(int(stored_id))
                channel = fetched if isinstance(fetched, discord.TextChannel) else None
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError, TypeError):
                channel = None
        if channel is None:
            channel = next((candidate for candidate in guild.text_channels
                            if candidate.name == channel_name and candidate.category_id == category.id), None)
    topic = f"ห้องส่วนตัวของทีมสมัครแข่งขัน #{reg_id} • {str(registration.get('team_name', 'Team'))[:120]}"
    created = channel is None
    if created:
        channel = await guild.create_text_channel(
            channel_name, category=category, topic=topic, overwrites=overwrites,
            reason=f"InveNOIR v15 create competition team chat #{reg_id}")
    else:
        await channel.edit(name=channel_name, category=category, topic=topic, overwrites=overwrites,
                           reason=f"InveNOIR v15 sync competition team chat #{reg_id}")
    if created:
        await channel.send(
            f"🔒 **INVENOIR — TEAM REGISTRATION**\n"
            f"ทีม: **{discord.utils.escape_markdown(str(registration.get('team_name', 'Team'))[:80])}**\n"
            f"สมาชิกที่ได้รับสิทธิ์เข้าห้อง: **{len(roster)} คน**\n"
            f"สถานะ: {team_registration_status_text(registration.get('status'))}\n\n"
            "ห้องนี้เป็นห้องส่วนตัวของทีมที่ส่งใบสมัครแข่งขันแล้ว ใช้คุยและเตรียมงานร่วมกันได้เลย\n"
            "ทีมงานจะตรวจใบสมัครในขั้นตอนถัดไปครับ 💜",
            allowed_mentions=discord.AllowedMentions.none())
    async with TEAM_FINDER_LOCK:
        data = team_data_load()
        stored = team_registration_get(data, reg_id)
        if stored is not None:
            stored["team_channel_id"] = channel.id
            team_data_save(data)
    return channel


async def lock_registered_team_channel(guild, registration):
    """After a declined entry, retain the history but remove access from the roster."""
    channel_id = int(registration.get("team_channel_id") or 0)
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None and channel_id:
        try:
            fetched = await guild.fetch_channel(channel_id)
            channel = fetched if isinstance(fetched, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            channel = None
    if channel is None:
        reg_prefix = f"registered-{int(registration.get('id', 0)):04d}-"
        closed_name = f"closed-team-{int(registration.get('id', 0)):04d}"
        channel = next((candidate for candidate in guild.text_channels
                        if candidate.name.startswith(reg_prefix) or candidate.name == closed_name), None)
    if channel is None:
        return False
    overwrites = {guild.default_role: discord.PermissionOverwrite(
        view_channel=False, send_messages=False, read_message_history=False)}
    for role_name in ("Organizer", "Staff", "Admin", "Administrator"):
        role = by_name(guild.roles, role_name)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False)
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True, manage_channels=True)
    await channel.edit(name=f"closed-team-{int(registration['id']):04d}"[:95],
                       topic=f"ใบสมัครแข่งขัน #{registration['id']} ไม่ผ่านการพิจารณา — ห้องถูกล็อก",
                       overwrites=overwrites, reason="InveNOIR v15 lock declined competition team room")
    await channel.send("🔒 ใบสมัครทีมนี้ถูกปิดแล้ว ห้องถูกล็อกและเก็บประวัติไว้สำหรับทีมงาน", allowed_mentions=discord.AllowedMentions.none())
    return True


async def create_team_competition_registration(guild, submitter, team_name, leader_id_raw,
                                               roster_raw, portfolios_raw, introduction):
    """Submit a complete team to the competition, independently of Group Finder."""
    team_name = str(team_name or "").strip()
    introduction = str(introduction or "").strip()
    if not team_name or len(team_name) > 80:
        return "❌ ชื่อทีมต้องมี 1–80 ตัวอักษร"
    if not introduction or len(introduction) > 1000:
        return "❌ กรุณาเขียนคอนเซปต์/แนะนำทีม 1–1000 ตัวอักษร"
    leader_id = registration_parse_discord_id(leader_id_raw)
    if leader_id is None:
        return "❌ Discord ID ของหัวหน้าทีมไม่ถูกต้อง กรุณาใส่ตัวเลข ID หรือ @mention"
    roster, roster_error = registration_parse_roster(roster_raw)
    if roster_error:
        return "❌ " + roster_error
    if leader_id not in {int(person["user_id"]) for person in roster}:
        return "❌ ต้องใส่หัวหน้าทีมไว้ในรายชื่อสมาชิกด้วย"
    roster, portfolio_error = registration_parse_portfolios(portfolios_raw, roster)
    if portfolio_error:
        return "❌ " + portfolio_error
    if submitter.id != leader_id and not is_staff_or_admin(submitter):
        return "❌ เพื่อยืนยันตัวตน หัวหน้าทีมต้องเป็นผู้ส่งใบสมัครเอง (หรือให้ Organizer/Staff ส่งแทน)"
    if not team_is_eligible(submitter) and not is_staff_or_admin(submitter):
        return "❌ ต้องมียศสายแข่งขันก่อนส่งใบสมัครทีม"
    member_objects = {}
    missing = []
    for person in roster:
        uid = int(person["user_id"])
        member = await team_fetch_member(guild, uid)
        if member is None:
            missing.append(str(uid))
        elif member.bot:
            return f"❌ Discord ID {uid} เป็นบัญชีบอท กรุณาใส่เฉพาะสมาชิกจริง"
        else:
            member_objects[uid] = member
    if missing:
        return "❌ ไม่พบ Discord ID นี้ในเซิร์ฟเวอร์: " + ", ".join(missing[:10]) + " — ให้สมาชิกเข้าร่วมเซิร์ฟเวอร์ก่อน"

    review_channel = await ensure_team_registration_review_channel(guild)
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านข้อมูลระบบไม่ได้: {str(exc)[:160]}"
        active = [item for item in data.get("competition_registrations", [])
                  if item.get("status") in {"pending", "processing", "approved", "channel_error"}]
        normalized_name = re.sub(r"\s+", " ", team_name).casefold()
        if any(re.sub(r"\s+", " ", str(item.get("team_name", "")).strip()).casefold() == normalized_name
               for item in active):
            return "❌ มีใบสมัครของชื่อทีมนี้ที่ยังดำเนินการอยู่แล้ว กรุณาติดต่อทีมงานหากเป็นการแก้ไขใบสมัครเดิม"
        submitted_ids = {int(person["user_id"]) for person in roster}
        for existing in active:
            existing_ids = {int(person.get("user_id", 0)) for person in existing.get("roster", [])}
            overlap = submitted_ids & existing_ids
            if overlap:
                return "❌ สมาชิกบางคนอยู่ในใบสมัครแข่งขันอื่นแล้ว: " + ", ".join(str(x) for x in sorted(overlap)[:8])
        reg_id = max([int(item.get("id", 0)) for item in data.get("competition_registrations", [])] + [0]) + 1
        registration = {
            "id": reg_id, "team_name": team_name, "leader_id": leader_id,
            "submitted_by": submitter.id, "roster": roster, "introduction": introduction,
            "status": "pending", "team_channel_id": None,
            "review_channel_id": review_channel.id, "review_message_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data.setdefault("competition_registrations", []).append(registration)
        data["next_competition_registration_id"] = reg_id + 1
        try:
            team_data_save(data)
        except OSError as exc:
            return f"❌ บันทึกใบสมัครทีมไม่ได้: {str(exc)[:160]}"
        registration_copy = dict(registration)

    channel = None
    channel_error = None
    try:
        channel = await ensure_registered_team_channel(guild, registration_copy)
        registration_copy["team_channel_id"] = channel.id
    except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        channel_error = f"{type(exc).__name__}: {str(exc)[:160]}"
        print(f"[InveNOIR Team Registration] Could not create team room #{reg_id}: {channel_error}", flush=True)
        async with TEAM_FINDER_LOCK:
            latest = team_data_load()
            stored = team_registration_get(latest, reg_id)
            if stored is not None:
                stored["status"] = "channel_error"
                team_data_save(latest)
                registration_copy = dict(stored)

    review_message = None
    try:
        review_message = await review_channel.send(
            content=f"📨 ใบสมัครทีมเข้าแข่งขันใหม่ **#{reg_id}** — **{team_name}**",
            embed=team_registration_embed(registration_copy),
            view=TeamRegistrationReviewView(reg_id),
            allowed_mentions=discord.AllowedMentions.none())
        async with TEAM_FINDER_LOCK:
            latest = team_data_load()
            stored = team_registration_get(latest, reg_id)
            if stored is not None:
                stored["review_message_id"] = review_message.id
                team_data_save(latest)
    except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[InveNOIR Team Registration] Could not post review #{reg_id}: {exc!r}", flush=True)

    if channel is not None:
        for member in member_objects.values():
            try:
                await member.send(
                    f"📝 ทีม **{team_name}** ส่งใบสมัครเข้าแข่งขัน InveNOIR แล้ว\n"
                    f"ห้องแชทส่วนตัวของทีม: {channel.mention}\n"
                    "สถานะตอนนี้: 🟡 รอทีมงานตรวจสอบ — ใช้ห้องนี้คุยเตรียมงานได้เลยครับ 💜",
                    allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.HTTPException):
                pass
    if channel_error:
        return (f"⚠️ บันทึกใบสมัครทีม **{team_name}** แล้ว (#{reg_id}) แต่สร้างห้องแชททีมไม่สำเร็จ\n"
                "ทีมงานสามารถใช้ `/team_registration_sync` เพื่อซ่อมระบบได้ครับ")
    return (f"✅ ส่งใบสมัครทีม **{team_name}** สำเร็จแล้ว (#{reg_id})\n"
            f"🔒 สร้างห้องแชทส่วนตัวให้สมาชิก {len(roster)} คนแล้ว: {channel.mention}\n"
            "สถานะ: 🟡 รอทีมงานตรวจสอบ ใบสมัครนี้แยกจาก Group Finder โดยสมบูรณ์ครับ 💜")


async def process_team_registration_decision(guild, registration_id, decision, actor):
    if not is_staff_or_admin(actor):
        return "❌ เฉพาะ Organizer, Staff หรือ Administrator เท่านั้นที่ตรวจใบสมัครทีมได้"
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านใบสมัครไม่ได้: {str(exc)[:160]}"
        registration = team_registration_get(data, registration_id)
        if registration is None:
            return "❌ ไม่พบใบสมัครทีมนี้"
        if registration.get("status") not in {"pending", "channel_error"}:
            return f"ใบสมัครนี้ถูกจัดการแล้วหรือกำลังดำเนินการ (สถานะ: {team_registration_status_text(registration.get('status'))})"
        registration["status"] = "processing"
        registration["reviewed_by"] = actor.id
        registration["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        registration_copy = dict(registration)
        team_data_save(data)

    if decision == "approve":
        try:
            channel = await ensure_registered_team_channel(guild, registration_copy)
        except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            async with TEAM_FINDER_LOCK:
                latest = team_data_load()
                stored = team_registration_get(latest, registration_id)
                if stored is not None:
                    stored["status"] = "pending"
                    team_data_save(latest)
            return f"❌ ยังยืนยันทีมไม่ได้ เพราะซิงก์ห้องทีมไม่สำเร็จ: {type(exc).__name__}: {str(exc)[:160]}"
        async with TEAM_FINDER_LOCK:
            latest = team_data_load()
            stored = team_registration_get(latest, registration_id)
            if stored is not None:
                stored["status"] = "approved"
                stored["team_channel_id"] = channel.id
                stored["approved_by"] = actor.id
                stored["approved_at"] = datetime.now(timezone.utc).isoformat()
                registration_copy = dict(stored)
                team_data_save(latest)
        try:
            await channel.send(
                f"🟢 **ทีม {registration_copy.get('team_name', 'Team')} ได้รับการยืนยันสมัครแข่งขันแล้ว!**\n"
                "ขอให้ใช้ห้องนี้ประสานงานและเตรียมผลงานร่วมกันครับ 💜",
                allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass
        for person in registration_copy.get("roster", []):
            member = await team_fetch_member(guild, int(person.get("user_id", 0)))
            if member is not None:
                try:
                    await member.send(
                        f"🟢 ใบสมัครทีม **{registration_copy.get('team_name', 'Team')}** ได้รับการยืนยันแล้ว!\n"
                        f"ห้องแชททีม: {channel.mention}",
                        allowed_mentions=discord.AllowedMentions.none())
                except (discord.Forbidden, discord.HTTPException):
                    pass
        return f"🟢 ยืนยันทีม **{registration_copy.get('team_name', 'Team')}** แล้ว\nห้องทีม: {channel.mention}"

    async with TEAM_FINDER_LOCK:
        latest = team_data_load()
        stored = team_registration_get(latest, registration_id)
        if stored is not None:
            stored["status"] = "declined"
            stored["declined_by"] = actor.id
            stored["declined_at"] = datetime.now(timezone.utc).isoformat()
            registration_copy = dict(stored)
            team_data_save(latest)
    locked = False
    try:
        locked = await lock_registered_team_channel(guild, registration_copy)
    except (discord.Forbidden, discord.HTTPException, ValueError, TypeError) as exc:
        print(f"[InveNOIR Team Registration] Could not lock declined room #{registration_id}: {exc!r}", flush=True)
    for person in registration_copy.get("roster", []):
        member = await team_fetch_member(guild, int(person.get("user_id", 0)))
        if member is not None:
            try:
                await member.send(
                    f"🔴 ใบสมัครทีม **{registration_copy.get('team_name', 'Team')}** ยังไม่ได้รับการอนุมัติจากทีมงาน\n"
                    "ห้องแชททีมถูกล็อกไว้แล้ว หากต้องการข้อมูลเพิ่มเติมกรุณาติดต่อ Organizer/Staff ครับ",
                    allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.HTTPException):
                pass
    return (f"🔴 ปิดใบสมัครทีม **{registration_copy.get('team_name', 'Team')}** แล้ว"
            + (" และล็อกห้องทีมเรียบร้อย" if locked else " แต่ล็อกห้องทีมไม่สำเร็จ กรุณาตรวจสิทธิ์บอท"))


class TeamRegistrationReviewView(discord.ui.View):
    def __init__(self, registration_id, disabled=False):
        super().__init__(timeout=None)
        self.registration_id = int(registration_id)
        approve = discord.ui.Button(label="✅ อนุมัติทีม", style=discord.ButtonStyle.success,
                                    custom_id=f"invenoir:teamregistration:approve:{self.registration_id}", disabled=disabled)
        approve.callback = self.approve_callback
        self.add_item(approve)
        decline = discord.ui.Button(label="❌ ไม่อนุมัติ", style=discord.ButtonStyle.danger,
                                    custom_id=f"invenoir:teamregistration:decline:{self.registration_id}", disabled=disabled)
        decline.callback = self.decline_callback
        self.add_item(decline)

    async def _decide(self, interaction, decision):
        if not interaction.guild or interaction.guild.id != GUILD_ID or not is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("❌ เฉพาะ Organizer / Staff / Administrator เท่านั้น", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await process_team_registration_decision(interaction.guild, self.registration_id, decision, interaction.user)
        try:
            data = team_data_load()
            registration = team_registration_get(data, self.registration_id)
            if registration and registration.get("status") in {"approved", "declined"} and interaction.message:
                await interaction.message.edit(embed=team_registration_embed(registration), view=TeamRegistrationReviewView(self.registration_id, disabled=True))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, discord.HTTPException, discord.Forbidden):
            pass
        await interaction.followup.send(result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def approve_callback(self, interaction):
        await self._decide(interaction, "approve")

    async def decline_callback(self, interaction):
        await self._decide(interaction, "decline")


class CompetitionTeamRegistrationModal(discord.ui.Modal):
    def __init__(self, suggested_leader_id=None):
        super().__init__(title="INVENOIR • TEAM REGISTRATION", timeout=600)
        self.team_name = discord.ui.TextInput(
            label="ชื่อทีม", placeholder="เช่น TEAM ECLIPSE", max_length=80)
        self.leader_id = discord.ui.TextInput(
            label="Discord ID ของหัวหน้าทีม", default=str(suggested_leader_id or ""),
            placeholder="ตัวเลข ID หรือ @mention", max_length=30)
        self.roster = discord.ui.TextInput(
            label="รายชื่อสมาชิก + ตำแหน่ง (1 คนต่อบรรทัด)",
            style=discord.TextStyle.paragraph, max_length=4000,
            placeholder="Discord ID | ชื่อในทีม | ตำแหน่ง\n123... | Bom | Vocalist\n456... | Alex | Mixer")
        self.portfolios = discord.ui.TextInput(
            label="ผลงานสมาชิก (ไม่บังคับ / 1 ลิงก์ต่อบรรทัด)",
            style=discord.TextStyle.paragraph, required=False, max_length=4000,
            placeholder="Discord ID | https://ลิงก์ผลงาน\nใส่ได้หลายบรรทัด และหลายลิงก์ต่อคน")
        self.introduction = discord.ui.TextInput(
            label="คอนเซปต์ / แนะนำทีม", style=discord.TextStyle.paragraph,
            max_length=1000, placeholder="แนะนำทีม แนวคิด และสิ่งที่อยากนำเสนอในการแข่งขัน")
        for item in (self.team_name, self.leader_id, self.roster, self.portfolios, self.introduction):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID:
            return await interaction.response.send_message("ใช้ได้เฉพาะใน InveNOIR Chorus Battle", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await create_team_competition_registration(
            interaction.guild, interaction.user, str(self.team_name.value), str(self.leader_id.value),
            str(self.roster.value), str(self.portfolios.value), str(self.introduction.value))
        await interaction.followup.send(result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class RegistrationApplicationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        submit = discord.ui.Button(label="📝 ลงทะเบียนทีมเข้าแข่งขัน", style=discord.ButtonStyle.primary,
                                   custom_id="invenoir:registration:team-submit")
        submit.callback = self.submit_callback
        self.add_item(submit)
        status = discord.ui.Button(label="📋 ตรวจสอบสถานะทีม", style=discord.ButtonStyle.secondary,
                                   custom_id="invenoir:registration:team-status")
        status.callback = self.status_callback
        self.add_item(status)

    async def submit_callback(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID:
            return await interaction.response.send_message("ใช้ได้เฉพาะใน InveNOIR Chorus Battle", ephemeral=True)
        if not team_is_eligible(interaction.user) and not is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("❌ ต้องมียศสายแข่งขันก่อนส่งใบสมัครทีม", ephemeral=True)
        await interaction.response.send_modal(CompetitionTeamRegistrationModal(interaction.user.id))

    async def status_callback(self, interaction: discord.Interaction):
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return await interaction.response.send_message(f"❌ อ่านสถานะไม่ได้: {str(exc)[:150]}", ephemeral=True)
        uid = interaction.user.id
        matches = [item for item in data.get("competition_registrations", [])
                   if int(item.get("leader_id", 0)) == uid or int(item.get("submitted_by", 0)) == uid
                   or any(int(person.get("user_id", 0)) == uid for person in item.get("roster", []))]
        if not matches:
            return await interaction.response.send_message("📭 ยังไม่พบใบสมัครทีมของคุณครับ", ephemeral=True)
        registration = max(matches, key=lambda item: int(item.get("id", 0)))
        channel_id = int(registration.get("team_channel_id") or 0)
        if registration.get("status") == "declined":
            room_text = "\n🔒 ห้องทีม: ถูกล็อกหลังใบสมัครไม่ผ่านการพิจารณา"
        else:
            room_text = f"\n🔒 ห้องทีม: <#{channel_id}>" if channel_id else "\n🔒 ห้องทีม: รอทีมงานตรวจสอบ/ซ่อมระบบ"
        await interaction.response.send_message(
            f"**INVENOIR — TEAM REGISTRATION #{registration['id']}**\n"
            f"ทีม: **{registration.get('team_name', 'Team')}**\n"
            f"สถานะ: {team_registration_status_text(registration.get('status'))}{room_text}",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def registration_application_panel_embed():
    embed = discord.Embed(
        title="INVENOIR — TEAM REGISTRATION",
        description=(
            "**ทีมของคุณรวมสมาชิกครบแล้ว และพร้อมสมัครเข้าแข่งขันใช่ไหม?**\n\n"
            "กดปุ่ม **ลงทะเบียนทีมเข้าแข่งขัน** แล้วกรอกข้อมูลในแบบฟอร์มได้เลย\n\n"
            "**ข้อมูลที่ต้องเตรียม**\n"
            "• ชื่อทีม และ Discord ID ของหัวหน้าทีม (ถ้าหัวหน้าทีมกดเอง ระบบเติม ID ให้)\n"
            "• รายชื่อสมาชิกทุกคน รวมถึงหัวหน้าทีม พร้อม Discord ID, ชื่อในทีม และตำแหน่ง\n"
            "• ลิงก์ผลงานของสมาชิก (ไม่บังคับ)\n"
            "• คอนเซปต์ / คำแนะนำทีม\n\n"
            "**รูปแบบรายชื่อสมาชิก**\n"
            "`Discord ID | ชื่อในทีม | ตำแหน่ง` (1 คนต่อ 1 บรรทัด)\n"
            "**รูปแบบผลงาน**\n"
            "`Discord ID | https://ลิงก์ผลงาน` (1 ลิงก์ต่อบรรทัด)\n\n"
            "เมื่อส่งใบสมัครสำเร็จ บอทจะสร้างห้องแชทส่วนตัวให้สมาชิกตาม Discord ID ที่กรอก และส่งใบสมัครให้ Organizer / Staff ตรวจสอบ\n"
            "ระบบนี้แยกจาก Group Finder — ไม่ต้องสร้างโพสต์หาทีมก่อนสมัครแข่งขัน"
        ),
        colour=discord.Colour(0x9C80DD), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="ขอบเขตสมาชิก", value="สูงสุด 20 คนต่อทีม • ทุกคนต้องอยู่ในเซิร์ฟเวอร์ • หัวหน้าทีมต้องเป็นผู้ส่งใบสมัครเอง (หรือให้ทีมงานส่งแทน)", inline=False)
    embed.set_footer(text="INVENOIR • OFFICIAL TEAM REGISTRATION")
    return embed


async def ensure_registration_application_panel(guild):
    channel = registration_text_channel(guild)
    if channel is None:
        raise ValueError("ไม่พบห้อง 📝・registration กรุณาตรวจสอบห้องในหมวด Chorus Battle")
    data = team_data_load()
    message = None
    stored_channel = data.get("registration_panel_channel_id")
    stored_message = data.get("registration_panel_message_id")
    if stored_channel and int(stored_channel) == channel.id and stored_message:
        try:
            message = await channel.fetch_message(int(stored_message))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError, TypeError):
            message = None
    if message is None:
        message = await channel.send(
            embed=registration_application_panel_embed(), view=RegistrationApplicationPanelView(),
            allowed_mentions=discord.AllowedMentions.none())
    else:
        await message.edit(embed=registration_application_panel_embed(), view=RegistrationApplicationPanelView(),
                           allowed_mentions=discord.AllowedMentions.none())
    data["registration_panel_channel_id"] = channel.id
    data["registration_panel_message_id"] = message.id
    team_data_save(data)
    return channel, message


class TeamFinderPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        create_btn = discord.ui.Button(label="📣 สร้างประกาศหาทีม", style=discord.ButtonStyle.primary,
                                       custom_id="invenoir:team:panel:create")
        create_btn.callback = self.create_callback
        self.add_item(create_btn)
        browse_btn = discord.ui.Button(label="🔎 ฉันกำลังหาทีม", style=discord.ButtonStyle.success,
                                       custom_id="invenoir:team:panel:browse")
        browse_btn.callback = self.browse_callback
        self.add_item(browse_btn)
        my_btn = discord.ui.Button(label="📋 ทีมของฉัน", style=discord.ButtonStyle.secondary,
                                   custom_id="invenoir:team:panel:my")
        my_btn.callback = self.my_team_callback
        self.add_item(my_btn)
        profiles_btn = discord.ui.Button(label="🪪 ดูคนกำลังหาทีม", style=discord.ButtonStyle.secondary,
                                         custom_id="invenoir:team:panel:profiles")
        profiles_btn.callback = self.profiles_callback
        self.add_item(profiles_btn)

    async def create_callback(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID or not team_is_eligible(interaction.user):
            return await interaction.response.send_message("❌ ต้องมียศสายแข่งขันก่อนสร้างประกาศใน Group Finder", ephemeral=True)
        try:
            data = team_data_load()
            existing = next((t for t in data["teams"] if int(t.get("owner_id", 0)) == interaction.user.id
                             and t.get("status") in TEAM_ACTIVE_STATUSES), None)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            existing = None
        if existing:
            return await interaction.response.send_message(
                f"คุณมีประกาศทีม **{existing['team_name']}** อยู่แล้ว ใช้ปุ่มแก้ไขในโพสต์เดิม หรือปิดประกาศก่อนสร้างโพสต์ใหม่ครับ",
                ephemeral=True)
        await interaction.response.send_modal(TeamCreateModal())

    async def browse_callback(self, interaction: discord.Interaction):
        await show_team_browse(interaction)

    async def profiles_callback(self, interaction: discord.Interaction):
        await show_profile_browse(interaction)

    async def my_team_callback(self, interaction: discord.Interaction):
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return await interaction.response.send_message(f"❌ อ่านข้อมูลทีมไม่ได้: {str(exc)[:160]}", ephemeral=True)
        owned = [t for t in data["teams"] if int(t.get("owner_id", 0)) == interaction.user.id and t.get("status") in TEAM_ACTIVE_STATUSES]
        pending = [a for a in data["applications"] if a.get("status") == "pending"
                   and any(int(t.get("thread_id", 0)) == int(a.get("team_thread_id", 0)) for t in owned)]
        if not owned:
            return await interaction.response.send_message("คุณยังไม่มีประกาศทีมที่เปิดอยู่ กด **สร้างประกาศหาทีม** เพื่อเริ่มได้เลยครับ", ephemeral=True)
        lines = []
        for team in owned[:10]:
            lines.append(f"• **{team['team_name']}** — {team_status_text(team['status'])} — <#{team['thread_id']}>")
        await interaction.response.send_message("📋 **ทีมของคุณ**\n" + "\n".join(lines) + f"\n\nคำขอที่รอพิจารณา: **{len(pending)}**\nใช้ `/team_applications` เพื่อดูผู้สมัคร", ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())


class MemberProfilePanelView(discord.ui.View):
    """Persistent panel for member profile creation and browsing."""
    def __init__(self):
        super().__init__(timeout=None)
        create_btn = discord.ui.Button(label="🪪 สร้าง / แก้ไขโปรไฟล์", style=discord.ButtonStyle.primary,
                                       custom_id="invenoir:profile:create")
        create_btn.callback = self.create_callback
        self.add_item(create_btn)
        browse_btn = discord.ui.Button(label="🔎 ดูคนที่กำลังหาทีม", style=discord.ButtonStyle.success,
                                       custom_id="invenoir:profile:browse")
        browse_btn.callback = self.browse_callback
        self.add_item(browse_btn)
        mine_btn = discord.ui.Button(label="👤 ดูโปรไฟล์ของฉัน", style=discord.ButtonStyle.secondary,
                                     custom_id="invenoir:profile:mine")
        mine_btn.callback = self.mine_callback
        self.add_item(mine_btn)

    async def create_callback(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID or not team_is_eligible(interaction.user):
            return await interaction.response.send_message("❌ ต้องมียศสายแข่งขันก่อนสร้างโปรไฟล์", ephemeral=True)
        try:
            profile = profile_get(team_data_load(), interaction.user.id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return await interaction.response.send_message(f"❌ อ่านโปรไฟล์ไม่ได้: {str(exc)[:150]}", ephemeral=True)
        await interaction.response.send_modal(MemberProfileModal(profile))

    async def browse_callback(self, interaction: discord.Interaction):
        await show_profile_browse(interaction)

    async def mine_callback(self, interaction: discord.Interaction):
        try:
            profile = profile_get(team_data_load(), interaction.user.id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return await interaction.response.send_message(f"❌ อ่านโปรไฟล์ไม่ได้: {str(exc)[:150]}", ephemeral=True)
        if profile is None:
            return await interaction.response.send_message("คุณยังไม่มีโปรไฟล์ กด **สร้าง / แก้ไขโปรไฟล์** ก่อนครับ", ephemeral=True)
        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        await interaction.response.send_message(embed=profile_embed(profile, member), view=ProfileManageView(), ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())


class MemberProfileModal(discord.ui.Modal):
    def __init__(self, profile=None):
        super().__init__(title="สร้าง / แก้ไขโปรไฟล์ • InveNOIR", timeout=300)
        profile = profile or {}
        self.alias = discord.ui.TextInput(label="นามแฝง / ชื่อที่ใช้ในผลงาน", default=str(profile.get("alias", ""))[:60],
                                         placeholder="เช่น Bom / Eclipse", max_length=60)
        self.specialties = discord.ui.TextInput(label="สายงาน / ทักษะ", default=str(profile.get("specialties", ""))[:180],
                                                placeholder="เช่น Vocalist, VTuber, Mixing", max_length=180)
        self.links = discord.ui.TextInput(label="ลิงก์ผลงาน (ลิงก์ละ 1 บรรทัด)", style=discord.TextStyle.paragraph,
                                          default="\n".join(profile.get("portfolio_links", []))[:1000],
                                          placeholder="https://...", required=False, max_length=1000)
        self.intro = discord.ui.TextInput(label="แนะนำตัว / จุดเด่น", style=discord.TextStyle.paragraph,
                                          default=str(profile.get("intro", ""))[:700],
                                          placeholder="บอกทีมอื่นว่าคุณถนัดอะไร", max_length=700)
        self.genres_availability = discord.ui.TextInput(label="แนวเพลง / เวลาที่สะดวก", style=discord.TextStyle.paragraph,
                                                        default=str(profile.get("genres_availability", ""))[:200],
                                                        placeholder="เช่น J-pop, Rock / เสาร์–อาทิตย์", max_length=200)
        for item in (self.alias, self.specialties, self.links, self.intro, self.genres_availability):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID or not team_is_eligible(interaction.user):
            return await interaction.response.send_message("❌ ต้องมียศสายแข่งขันก่อนสร้างโปรไฟล์", ephemeral=True)
        values = [str(self.alias.value).strip(), str(self.specialties.value).strip(),
                  str(self.links.value).strip(), str(self.intro.value).strip(),
                  str(self.genres_availability.value).strip()]
        invalid = profile_validate_fields(*values)
        if invalid:
            return await interaction.response.send_message("❌ " + invalid, ephemeral=True)
        links, link_error = profile_parse_links(values[2])
        if link_error:
            return await interaction.response.send_message("❌ " + link_error, ephemeral=True)
        async with TEAM_FINDER_LOCK:
            try:
                data = team_data_load()
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return await interaction.response.send_message(f"❌ อ่านข้อมูลโปรไฟล์ไม่ได้: {str(exc)[:150]}", ephemeral=True)
            old = profile_get(data, interaction.user.id)
            active_team = member_active_team(data, interaction.user.id)
            default_looking = bool(old.get("looking_for_team", True)) if old else active_team is None
            if active_team is not None:
                default_looking = False
            profile = {
                "user_id": interaction.user.id,
                "alias": values[0],
                "specialties": values[1],
                "portfolio_links": links or [],
                "intro": values[3],
                "genres_availability": values[4],
                "looking_for_team": default_looking,
                "created_at": old.get("created_at", datetime.now(timezone.utc).isoformat()) if old else datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            data["profiles"] = [p for p in data.get("profiles", []) if int(p.get("user_id", 0)) != interaction.user.id]
            data["profiles"].append(profile)
            teams_to_refresh = [dict(t) for t in data.get("teams", [])
                                if t.get("status") in TEAM_ACTIVE_STATUSES
                                and (int(t.get("owner_id", 0)) == interaction.user.id
                                     or interaction.user.id in {int(x) for x in t.get("accepted_members", [])})]
            try:
                team_data_save(data)
            except OSError as exc:
                return await interaction.response.send_message(f"❌ บันทึกโปรไฟล์ไม่ได้: {str(exc)[:150]}", ephemeral=True)
        await interaction.response.send_message("✅ บันทึกโปรไฟล์แล้ว! ทีมที่กำลังหาสมาชิกสามารถดูโปรไฟล์และส่งคำเชิญให้คุณได้", 
                                                embed=profile_embed(profile, interaction.user), view=ProfileManageView(), ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
        for team in teams_to_refresh:
            await team_refresh_post(interaction.guild, team)


class ProfileManageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        edit_btn = discord.ui.Button(label="✏️ แก้ไขโปรไฟล์", style=discord.ButtonStyle.primary,
                                     custom_id="invenoir:profile:manage:edit")
        edit_btn.callback = self.edit_callback
        self.add_item(edit_btn)
        toggle_btn = discord.ui.Button(label="🔄 เปิด / ปิดสถานะหาทีม", style=discord.ButtonStyle.secondary,
                                       custom_id="invenoir:profile:manage:toggle")
        toggle_btn.callback = self.toggle_callback
        self.add_item(toggle_btn)

    async def edit_callback(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID or not team_is_eligible(interaction.user):
            return await interaction.response.send_message("❌ ต้องมียศสายแข่งขันก่อนแก้ไขโปรไฟล์", ephemeral=True)
        try:
            profile = profile_get(team_data_load(), interaction.user.id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return await interaction.response.send_message(f"❌ อ่านโปรไฟล์ไม่ได้: {str(exc)[:150]}", ephemeral=True)
        await interaction.response.send_modal(MemberProfileModal(profile))

    async def toggle_callback(self, interaction: discord.Interaction):
        async with TEAM_FINDER_LOCK:
            try:
                data = team_data_load()
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return await interaction.response.send_message(f"❌ อ่านโปรไฟล์ไม่ได้: {str(exc)[:150]}", ephemeral=True)
            profile = profile_get(data, interaction.user.id)
            if profile is None:
                return await interaction.response.send_message("คุณยังไม่มีโปรไฟล์ครับ", ephemeral=True)
            new_status = not bool(profile.get("looking_for_team", True))
            if new_status:
                active = member_active_team(data, interaction.user.id)
                if active is not None:
                    return await interaction.response.send_message(f"คุณอยู่ในทีม **{active.get('team_name', 'ทีม')}** แล้ว จึงเปิดหาทีมใหม่ไม่ได้", ephemeral=True)
            profile["looking_for_team"] = new_status
            profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            team_data_save(data)
            profile_copy = dict(profile)
        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        state = "🟢 เปิดสถานะกำลังหาทีมแล้ว ทีมอื่นสามารถค้นหาโปรไฟล์คุณได้" if new_status else "⚪ ปิดสถานะหาทีมแล้ว โปรไฟล์จะไม่ปรากฏในรายชื่อคนที่กำลังหาทีม"
        await interaction.response.send_message(state, embed=profile_embed(profile_copy, member), view=self,
                                                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class ProfileBrowseView(discord.ui.View):
    """Large, paginated member profile cards; no dropdown/select menu."""
    def __init__(self, profiles, owner_id=None, index=0):
        super().__init__(timeout=300)
        self.profiles = [dict(p) for p in profiles]
        self.owner_id = int(owner_id) if owner_id else None
        self.index = max(0, min(int(index), max(0, len(self.profiles) - 1)))
        self.prev_btn = discord.ui.Button(label="◀ ก่อนหน้า", style=discord.ButtonStyle.secondary,
                                          disabled=self.index <= 0)
        self.prev_btn.callback = self.previous_callback
        self.add_item(self.prev_btn)
        self.next_btn = discord.ui.Button(label="ถัดไป ▶", style=discord.ButtonStyle.secondary,
                                          disabled=self.index >= len(self.profiles) - 1)
        self.next_btn.callback = self.next_callback
        self.add_item(self.next_btn)
        invite_btn = discord.ui.Button(label="✉️ เชิญเข้าทีมของฉัน", style=discord.ButtonStyle.success,
                                       disabled=not self.profiles)
        invite_btn.callback = self.invite_callback
        self.add_item(invite_btn)
        close_btn = discord.ui.Button(label="✖ ปิด", style=discord.ButtonStyle.danger)
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    def current_profile(self):
        return self.profiles[self.index] if self.profiles else None

    async def _check_owner(self, interaction):
        if self.owner_id is not None and interaction.user.id != self.owner_id:
            await interaction.response.send_message("แผงค้นหานี้เป็นของผู้ที่เปิดใช้งาน กรุณาเปิดรายการของคุณเอง", ephemeral=True)
            return False
        return True

    async def _edit_card(self, interaction):
        profile = self.current_profile()
        if profile is None:
            return await interaction.response.edit_message(content="ไม่พบโปรไฟล์", embed=None, view=None)
        member = await team_fetch_member(interaction.guild, int(profile["user_id"])) if interaction.guild else None
        embed = profile_embed(profile, member)
        embed.set_footer(text=f"INVENOIR • PROFILE {self.index + 1}/{len(self.profiles)} • กดก่อนหน้า/ถัดไปเพื่อดูคนอื่น")
        self.prev_btn.disabled = self.index <= 0
        self.next_btn.disabled = self.index >= len(self.profiles) - 1
        await interaction.response.edit_message(content="🪪 **โปรไฟล์สมาชิกที่กำลังหาทีม**", embed=embed, view=self,
                                                allowed_mentions=discord.AllowedMentions.none())

    async def _move(self, interaction, delta):
        if not await self._check_owner(interaction):
            return
        self.index = max(0, min(self.index + delta, len(self.profiles) - 1))
        await self._edit_card(interaction)

    async def previous_callback(self, interaction):
        await self._move(interaction, -1)

    async def next_callback(self, interaction):
        await self._move(interaction, 1)

    async def invite_callback(self, interaction):
        if not await self._check_owner(interaction):
            return
        profile = self.current_profile()
        if profile is None:
            return await interaction.response.send_message("ไม่พบโปรไฟล์", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await create_team_invitation(interaction.guild, interaction.user, int(profile["user_id"]))
        await interaction.followup.send(result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def close_callback(self, interaction):
        if not await self._check_owner(interaction):
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="ปิดหน้าต่างค้นหาโปรไฟล์แล้ว", embed=None, view=self)


class ProfileSelectedView(discord.ui.View):
    def __init__(self, target_user_id):
        super().__init__(timeout=180)
        self.target_user_id = int(target_user_id)
        invite_btn = discord.ui.Button(label="✉️ เชิญเข้าทีมของฉัน", style=discord.ButtonStyle.success)
        invite_btn.callback = self.invite_callback
        self.add_item(invite_btn)

    async def invite_callback(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != GUILD_ID:
            return await interaction.response.send_message("ใช้ได้เฉพาะในเซิร์ฟเวอร์ InveNOIR", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await create_team_invitation(interaction.guild, interaction.user, self.target_user_id)
        await interaction.followup.send(result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class TeamInvitationView(discord.ui.View):
    def __init__(self, invitation_id, disabled=False):
        super().__init__(timeout=None)
        self.invitation_id = int(invitation_id)
        accept_btn = discord.ui.Button(label="✅ รับคำเชิญ", style=discord.ButtonStyle.success,
                                       custom_id=f"invenoir:teaminvite:accept:{self.invitation_id}", disabled=disabled)
        accept_btn.callback = self.accept_callback
        self.add_item(accept_btn)
        decline_btn = discord.ui.Button(label="🚫 ปฏิเสธ", style=discord.ButtonStyle.danger,
                                        custom_id=f"invenoir:teaminvite:decline:{self.invitation_id}", disabled=disabled)
        decline_btn.callback = self.decline_callback
        self.add_item(decline_btn)

    async def _decide(self, interaction, decision):
        guild = client.get_guild(GUILD_ID)
        if guild is None:
            return await interaction.response.send_message("❌ บอทไม่พบเซิร์ฟเวอร์ กรุณาลองใหม่", ephemeral=bool(interaction.guild))
        try:
            data = team_data_load()
            invitation = team_get_invitation(data, self.invitation_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            invitation = None
        if invitation is None or int(invitation.get("applicant_id", 0)) != interaction.user.id:
            return await interaction.response.send_message("❌ คำเชิญนี้ไม่ใช่ของบัญชีคุณ หรือไม่พบคำเชิญ", ephemeral=bool(interaction.guild))
        await interaction.response.defer(ephemeral=bool(interaction.guild), thinking=True)
        result = await process_team_invitation_decision(guild, self.invitation_id, decision, interaction.user.id)
        try:
            latest = team_get_invitation(team_data_load(), self.invitation_id)
            if interaction.message and latest and latest.get("status") != "pending":
                await interaction.message.edit(view=TeamInvitationView(self.invitation_id, disabled=True))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, discord.HTTPException, discord.Forbidden):
            pass
        await interaction.followup.send(result, ephemeral=bool(interaction.guild), allowed_mentions=discord.AllowedMentions.none())

    async def accept_callback(self, interaction: discord.Interaction):
        await self._decide(interaction, "accept")

    async def decline_callback(self, interaction: discord.Interaction):
        await self._decide(interaction, "decline")


async def create_team_invitation(guild, inviter, target_user_id):
    if not team_is_eligible(inviter):
        return "❌ ต้องมียศสายแข่งขันก่อนส่งคำเชิญ"
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านข้อมูลทีมไม่ได้: {str(exc)[:160]}"
        team = next((t for t in data["teams"] if int(t.get("owner_id", 0)) == inviter.id
                     and t.get("status") == "recruiting"), None)
        if team is None:
            return "❌ คุณต้องเป็นหัวหน้าทีมที่กำลังเปิดรับสมาชิกก่อน จึงจะเชิญคนเข้าทีมได้"
        target_user_id = int(target_user_id)
        if target_user_id == inviter.id or target_user_id in {int(x) for x in team.get("accepted_members", [])}:
            return "สมาชิกคนนี้อยู่ในทีมคุณแล้ว"
        profile = profile_get(data, target_user_id)
        if profile is None or not profile.get("looking_for_team", True):
            return "⚪ โปรไฟล์นี้ไม่ได้เปิดสถานะหาทีมแล้ว"
        active = member_active_team(data, target_user_id)
        if active is not None:
            return f"สมาชิกคนนี้อยู่ในทีม **{active.get('team_name', 'ทีม')}** แล้ว"
        previous = next((inv for inv in data.get("invitations", [])
                         if int(inv.get("team_thread_id", 0)) == int(team["thread_id"])
                         and int(inv.get("applicant_id", 0)) == target_user_id
                         and inv.get("status") == "pending"), None)
        if previous:
            return "คุณส่งคำเชิญให้สมาชิกคนนี้ไปแล้ว และกำลังรอคำตอบ"
        invitation_id = max([int(i.get("id", 0)) for i in data.get("invitations", [])] + [0]) + 1
        invitation = {
            "id": invitation_id, "team_thread_id": int(team["thread_id"]), "team_name": team["team_name"],
            "team_owner_id": int(team["owner_id"]), "applicant_id": target_user_id,
            "status": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data.setdefault("invitations", []).append(invitation)
        data["next_invitation_id"] = invitation_id + 1
        try:
            team_data_save(data)
        except OSError as exc:
            return f"❌ บันทึกคำเชิญไม่ได้: {str(exc)[:160]}"
        team_copy, invitation_copy = dict(team), dict(invitation)
    target = await team_fetch_member(guild, target_user_id)
    if target is None:
        return "⚠️ ไม่พบสมาชิกในเซิร์ฟเวอร์ จึงยังส่งคำเชิญไม่ได้"
    embed = discord.Embed(
        title="✉️ มีทีมเชิญคุณเข้าร่วม!",
        description=f"ทีม **{team_copy['team_name']}** สนใจโปรไฟล์ของคุณและอยากชวนเข้าทีม\n\nคุณเลือกได้ว่าจะรับหรือปฏิเสธคำเชิญ",
        colour=discord.Colour(0x9C80DD), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="กำลังหา", value=str(team_copy.get("looking_for", "ยังไม่ระบุ"))[:1024], inline=False)
    embed.add_field(name="เวลาที่สะดวก", value=str(team_copy.get("availability", "ยังไม่ระบุ"))[:1024], inline=True)
    try:
        await target.send(embed=embed, view=TeamInvitationView(invitation_id), allowed_mentions=discord.AllowedMentions.none())
        return f"✅ ส่งคำเชิญให้โปรไฟล์นี้แล้ว หัวหน้าทีมจะเห็นผลเมื่อสมาชิกตอบกลับ (คำเชิญ #{invitation_id})"
    except (discord.Forbidden, discord.HTTPException):
        async with TEAM_FINDER_LOCK:
            try:
                latest_data = team_data_load()
                latest = team_get_invitation(latest_data, invitation_id)
                if latest and latest.get("status") == "pending":
                    latest["status"] = "delivery_failed"
                    team_data_save(latest_data)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        return "⚠️ บันทึกคำเชิญไม่สำเร็จเพราะส่ง DM ไม่ได้ สมาชิกอาจปิด DM จากเซิร์ฟเวอร์ ต้องให้เขาเปิด DM หรือสมัครเข้าทีมจากโพสต์ทีมแทน"


async def process_team_invitation_decision(guild, invitation_id, decision, actor_id):
    async with TEAM_FINDER_LOCK:
        try:
            data = team_data_load()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return f"❌ อ่านคำเชิญไม่ได้: {str(exc)[:160]}"
        invitation = team_get_invitation(data, invitation_id)
        if invitation is None:
            return "❌ ไม่พบคำเชิญนี้"
        if int(invitation.get("applicant_id", 0)) != int(actor_id):
            return "❌ คำเชิญนี้ไม่ได้ส่งถึงคุณ"
        if invitation.get("status") != "pending":
            return f"คำเชิญนี้ถูกจัดการไปแล้ว (สถานะ: {invitation.get('status')})"
        team = team_get(data, invitation["team_thread_id"])
        if team is None:
            invitation["status"] = "cancelled"
            team_data_save(data)
            return "❌ ไม่พบทีมเดิม คำเชิญนี้ถูกยกเลิก"
        applicant_id = int(invitation["applicant_id"])
        if decision == "accept":
            if team.get("status") != "recruiting":
                return "🔒 ทีมนี้ไม่ได้เปิดรับสมาชิกแล้ว จึงรับคำเชิญนี้ไม่ได้"
            active = member_active_team(data, applicant_id, exclude_thread_id=int(invitation["team_thread_id"]))
            if active is not None:
                return f"❌ คุณอยู่ในทีม **{active.get('team_name', 'ทีม')}** แล้ว จึงรับคำเชิญซ้ำไม่ได้"
            accepted = team.setdefault("accepted_members", [])
            if applicant_id not in {int(x) for x in accepted}:
                accepted.append(applicant_id)
            profile = profile_get(data, applicant_id)
            if profile is not None:
                profile["looking_for_team"] = False
                profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            for other_app in data.get("applications", []):
                if (int(other_app.get("applicant_id", 0)) == applicant_id
                        and other_app.get("status") == "pending"):
                    other_app["status"] = "cancelled"
                    other_app["decided_at"] = datetime.now(timezone.utc).isoformat()
            for other_invite in data.get("invitations", []):
                if (int(other_invite.get("applicant_id", 0)) == applicant_id
                        and other_invite.get("status") == "pending"
                        and int(other_invite.get("id", 0)) != int(invitation_id)):
                    other_invite["status"] = "cancelled"
                    other_invite["decided_at"] = datetime.now(timezone.utc).isoformat()
            invitation["status"] = "accepted"
        else:
            invitation["status"] = "declined"
        invitation["decided_at"] = datetime.now(timezone.utc).isoformat()
        team_copy, invitation_copy = dict(team), dict(invitation)
        team_data_save(data)
    owner = await team_fetch_member(guild, int(invitation_copy["team_owner_id"]))
    applicant = await team_fetch_member(guild, applicant_id)
    if decision == "decline":
        if owner:
            try:
                await owner.send(f"ℹ️ สมาชิกที่คุณเชิญปฏิเสธคำเชิญเข้าทีม **{team_copy['team_name']}** แล้ว")
            except (discord.Forbidden, discord.HTTPException):
                pass
        return f"คุณปฏิเสธคำเชิญเข้าทีม **{team_copy['team_name']}** แล้ว"
    await team_refresh_post(guild, team_copy)
    thread_url = await create_private_team_coordination(guild, team_copy, invitation_copy)
    if owner:
        try:
            await owner.send(f"🎉 <@{applicant_id}> ตอบรับคำเชิญเข้าทีม **{team_copy['team_name']}** แล้ว!" +
                             (f"\nห้องคุยทีม: {thread_url}" if thread_url else ""),
                             allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass
    return f"🎉 คุณตอบรับคำเชิญเข้าทีม **{team_copy['team_name']}** แล้ว!" + (f"\nห้องคุยทีม: {thread_url}" if thread_url else "\nทีมงานหรือหัวหน้าทีมจะติดต่อคุณเพื่อประสานงานต่อ")


async def show_profile_browse(interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID:
        return await interaction.response.send_message("ใช้ได้เฉพาะใน InveNOIR Chorus Battle", ephemeral=True)
    try:
        data = team_data_load()
        profiles = [p for p in data.get("profiles", []) if p.get("looking_for_team", True)
                    and member_active_team(data, int(p.get("user_id", 0))) is None]
        profiles.sort(key=lambda p: p.get("updated_at", p.get("created_at", "")), reverse=True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return await interaction.response.send_message(f"❌ อ่านรายชื่อโปรไฟล์ไม่ได้: {str(exc)[:160]}", ephemeral=True)
    if not profiles:
        return await interaction.response.send_message("📭 ตอนนี้ยังไม่มีโปรไฟล์ที่เปิดสถานะหาทีมอยู่\nสมาชิกสามารถไปที่ `👤・member-profiles` แล้วกด **สร้าง / แก้ไขโปรไฟล์** ได้ครับ", ephemeral=True)
    member = await team_fetch_member(interaction.guild, int(profiles[0]["user_id"]))
    first_embed = profile_embed(profiles[0], member)
    first_embed.set_footer(text=f"INVENOIR • PROFILE 1/{len(profiles)} • ใช้ปุ่มก่อนหน้า/ถัดไปเพื่อดูคนอื่น")
    await interaction.response.send_message(
        content="🔎 **สมาชิกที่กำลังหาทีม** — ดูโปรไฟล์ทีละคนและเลื่อนด้วยปุ่ม ไม่ต้องเลือกจาก Dropdown",
        embed=first_embed, view=ProfileBrowseView(profiles, owner_id=interaction.user.id), ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


class TeamApplicationDecisionView(discord.ui.View):
    def __init__(self, application_id, disabled=False):
        super().__init__(timeout=None)
        self.application_id = int(application_id)
        accept_btn = discord.ui.Button(label="✅ Accept", style=discord.ButtonStyle.success,
                                       custom_id=f"invenoir:teamapp:accept:{self.application_id}", disabled=disabled)
        accept_btn.callback = self.accept_callback
        self.add_item(accept_btn)
        decline_btn = discord.ui.Button(label="🚫 Decline", style=discord.ButtonStyle.danger,
                                        custom_id=f"invenoir:teamapp:decline:{self.application_id}", disabled=disabled)
        decline_btn.callback = self.decline_callback
        self.add_item(decline_btn)

    async def _decide(self, interaction, decision):
        guild = client.get_guild(GUILD_ID)
        if guild is None:
            return await interaction.response.send_message("❌ บอทไม่พบเซิร์ฟเวอร์ กรุณาลองใหม่", ephemeral=True)
        try:
            data = team_data_load()
            app = team_get_application(data, self.application_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            app = None
        if app is None:
            return await interaction.response.send_message("❌ ไม่พบคำขอนี้", ephemeral=bool(interaction.guild))
        # DM decision buttons are delivered to the team owner; do not allow a forwarded message to grant access.
        if int(app.get("team_owner_id", 0)) != interaction.user.id:
            return await interaction.response.send_message("❌ ปุ่มนี้ใช้ได้เฉพาะหัวหน้าทีมที่ได้รับคำขอ", ephemeral=bool(interaction.guild))
        await interaction.response.defer(thinking=True, ephemeral=bool(interaction.guild))
        result = await process_team_application_decision(guild, self.application_id, decision, interaction.user.id, allow_staff=False)
        try:
            current_data = team_data_load()
            current_app = team_get_application(current_data, self.application_id)
            if interaction.message and current_app and current_app.get("status") != "pending":
                await interaction.message.edit(view=TeamApplicationDecisionView(self.application_id, disabled=True))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, discord.HTTPException, discord.Forbidden):
            pass
        await interaction.followup.send(result, ephemeral=bool(interaction.guild), allowed_mentions=discord.AllowedMentions.none())

    async def accept_callback(self, interaction: discord.Interaction):
        await self._decide(interaction, "accept")

    async def decline_callback(self, interaction: discord.Interaction):
        await self._decide(interaction, "decline")


@client.tree.command(name="team_board", description="สร้างหรืออัปเดตแผงลงทีม/หาทีมและโปรไฟล์สมาชิก", guild=TARGET_GUILD)
async def team_board(interaction: discord.Interaction):
    if not can_announce(interaction):
        return await interaction.response.send_message("❌ เฉพาะ Organizer, Staff หรือผู้ดูแลเท่านั้น", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await ensure_rooms(interaction.guild)
        forum = team_finder_forum(interaction.guild)
        if forum is None:
            return await interaction.followup.send("❌ ไม่พบห้อง `group-finder` ที่เป็น Forum หรือ Text Channel", ephemeral=True)
        data = team_data_load()
        board_thread = None
        if data.get("board_thread_id"):
            board_thread = await team_fetch_thread(interaction.guild, data["board_thread_id"])
        if board_thread is not None:
            if board_thread.archived:
                await board_thread.edit(archived=False, reason="Refresh Team Finder v15 panel")
            message_id = int(data.get("board_message_id") or board_thread.id)
            message = await board_thread.fetch_message(message_id)
            await message.edit(content="📌 **INVENOIR • GROUP FINDER**\nค้นหาทีม • ค้นหาสมาชิก • สร้างประกาศรับสมัคร • จัดการโปรไฟล์\n_ระบบนี้ใช้สำหรับจับคู่สมาชิก ไม่ใช่การสมัครแข่งขันอย่างเป็นทางการ_",
                               embed=team_panel_embed(), view=TeamFinderPanelView(),
                               allowed_mentions=discord.AllowedMentions.none())
            thread = board_thread
        else:
            thread, message = await create_team_finder_thread(
                forum,
                name=TEAM_FINDER_PANEL_NAME,
                content="📌 **INVENOIR • GROUP FINDER**\nค้นหาทีม • ค้นหาสมาชิก • สร้างประกาศรับสมัคร • จัดการโปรไฟล์\n_ระบบนี้ใช้สำหรับจับคู่สมาชิก ไม่ใช่การสมัครแข่งขันอย่างเป็นทางการ_",
                embeds=[team_panel_embed()], view=TeamFinderPanelView(),
                reason="InveNOIR v15 Group Finder control panel",
            )
            data["board_thread_id"], data["board_message_id"] = thread.id, message.id
            team_data_save(data)
        profile_channel, profile_message = await ensure_profile_board(interaction.guild)
        await interaction.followup.send(
            f"✅ Group Finder Dashboard พร้อมใช้งาน: {thread.jump_url}\n"
            f"🪪 Member Profile พร้อมใช้งาน: {profile_channel.mention} ({profile_message.jump_url})\n"
            "🔒 โปรไฟล์จำกัดการมองเห็นเฉพาะสายงานที่เกี่ยวข้องกับการแข่งขัน\n"
            "🤝 การสมัครใช้โปรไฟล์ที่บันทึกไว้ และสร้าง Team Chat หลังหัวหน้าทีมตอบรับเท่านั้น",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    except (discord.HTTPException, discord.Forbidden, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        traceback.print_exc()
        await interaction.followup.send(f"❌ สร้าง/อัปเดตกระดานไม่ได้: {type(exc).__name__}: {str(exc)[:250]}", ephemeral=True)


@client.tree.command(name="registration_panel", description="สร้างหรืออัปเดตแผงลงทะเบียนทีมเข้าแข่งขันในห้อง registration", guild=TARGET_GUILD)
async def registration_panel(interaction: discord.Interaction):
    if not can_announce(interaction):
        return await interaction.response.send_message("❌ เฉพาะ Organizer, Staff หรือผู้ดูแลเท่านั้น", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        channel, message = await ensure_registration_application_panel(interaction.guild)
        await interaction.followup.send(f"✅ แผงลงทะเบียนทีมเข้าแข่งขันพร้อมใช้งานใน {channel.mention}\n{message.jump_url}",
                                        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    except (discord.HTTPException, discord.Forbidden, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        await interaction.followup.send(f"❌ สร้างแผงสมัครไม่ได้: {type(exc).__name__}: {str(exc)[:220]}", ephemeral=True)


@client.tree.command(name="team_registrations", description="ดูใบสมัครทีมเข้าแข่งขันที่รอทีมงานตรวจสอบ", guild=TARGET_GUILD)
async def team_registrations(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID or not is_staff_or_admin(interaction.user):
        return await interaction.response.send_message("❌ เฉพาะ Organizer / Staff / Administrator เท่านั้น", ephemeral=True)
    try:
        data = team_data_load()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return await interaction.response.send_message(f"❌ อ่านรายการไม่ได้: {str(exc)[:150]}", ephemeral=True)
    items = [item for item in data.get("competition_registrations", []) if item.get("status") in {"pending", "channel_error", "processing"}]
    if not items:
        return await interaction.response.send_message("📭 ไม่มีใบสมัครทีมเข้าแข่งขันที่รอตรวจสอบ", ephemeral=True)
    lines = []
    for item in items[:20]:
        room_id = int(item.get("team_channel_id") or 0)
        room = f" • <#{room_id}>" if room_id else " • ยังไม่มีห้องทีม"
        lines.append(f"• **#{item['id']} {item.get('team_name', 'Team')}** — {team_registration_status_text(item.get('status'))}{room}")
    await interaction.response.send_message("📝 **ใบสมัครทีมเข้าแข่งขันที่รอตรวจสอบ**\n" + "\n".join(lines)[:1850],
                                            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="team_registration_sync", description="ซ่อมห้องทีมและแผงตรวจใบสมัครทีมเข้าแข่งขัน", guild=TARGET_GUILD)
async def team_registration_sync(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID or not is_staff_or_admin(interaction.user):
        return await interaction.response.send_message("❌ เฉพาะ Organizer / Staff / Administrator เท่านั้น", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        review_channel = await ensure_team_registration_review_channel(interaction.guild)
        await ensure_registered_teams_category(interaction.guild)
        data = team_data_load()
        items = [dict(item) for item in data.get("competition_registrations", [])
                 if item.get("status") in {"pending", "channel_error", "processing", "approved", "declined"}]
        fixed_rooms, fixed_posts, errors = 0, 0, []
        for item in items:
            try:
                if item.get("status") == "declined":
                    if await lock_registered_team_channel(interaction.guild, item):
                        fixed_rooms += 1
                    continue
                room = await ensure_registered_team_channel(interaction.guild, item)
                if room:
                    fixed_rooms += 1
                if item.get("status") in {"pending", "channel_error", "processing"}:
                    latest = team_data_load()
                    stored = team_registration_get(latest, int(item["id"]))
                    if stored is not None:
                        stored["status"] = "pending"
                        if stored.get("review_message_id"):
                            try:
                                message = await review_channel.fetch_message(int(stored["review_message_id"]))
                                await message.edit(embed=team_registration_embed(stored),
                                                   view=TeamRegistrationReviewView(int(item["id"])),
                                                   allowed_mentions=discord.AllowedMentions.none())
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError, TypeError):
                                message = None
                        else:
                            message = None
                        if message is None:
                            message = await review_channel.send(
                                content=f"📨 ใบสมัครทีมเข้าแข่งขัน **#{item['id']}** — **{item.get('team_name', 'Team')}**",
                                embed=team_registration_embed(stored),
                                view=TeamRegistrationReviewView(int(item["id"])),
                                allowed_mentions=discord.AllowedMentions.none())
                            stored["review_message_id"] = message.id
                            stored["review_channel_id"] = review_channel.id
                            fixed_posts += 1
                        team_data_save(latest)
            except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                errors.append(f"#{item.get('id')}: {type(exc).__name__}")
        message = f"🔧 ซิงก์ระบบ Team Registration แล้ว • ห้องทีม {fixed_rooms} ห้อง • โพสต์ตรวจใบสมัครใหม่/อัปเดต {fixed_posts} รายการ"
        if errors:
            message += "\n⚠️ " + ", ".join(errors[:8])
        await interaction.followup.send(message[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        await interaction.followup.send(f"❌ ซิงก์ระบบไม่ได้: {type(exc).__name__}: {str(exc)[:200]}", ephemeral=True)


@client.tree.command(name="my_team_registration", description="ตรวจสอบสถานะใบสมัครทีมแข่งขันของฉัน", guild=TARGET_GUILD)
async def my_team_registration(interaction: discord.Interaction):
    try:
        data = team_data_load()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return await interaction.response.send_message(f"❌ อ่านสถานะไม่ได้: {str(exc)[:150]}", ephemeral=True)
    uid = interaction.user.id
    matches = [item for item in data.get("competition_registrations", [])
               if int(item.get("leader_id", 0)) == uid or int(item.get("submitted_by", 0)) == uid
               or any(int(person.get("user_id", 0)) == uid for person in item.get("roster", []))]
    if not matches:
        return await interaction.response.send_message("📭 ยังไม่พบใบสมัครทีมของคุณครับ", ephemeral=True)
    registration = max(matches, key=lambda item: int(item.get("id", 0)))
    channel_id = int(registration.get("team_channel_id") or 0)
    if registration.get("status") == "declined":
        room_text = "\n🔒 ห้องทีม: ถูกล็อกหลังใบสมัครไม่ผ่านการพิจารณา"
    else:
        room_text = f"\n🔒 ห้องทีม: <#{channel_id}>" if channel_id else "\n🔒 ห้องทีม: ยังไม่พร้อม"
    await interaction.response.send_message(
        f"**INVENOIR — TEAM REGISTRATION #{registration['id']}**\n"
        f"ทีม: **{registration.get('team_name', 'Team')}**\n"
        f"สถานะ: {team_registration_status_text(registration.get('status'))}{room_text}",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="profile_board", description="สร้างหรืออัปเดตห้อง/แผงสร้างโปรไฟล์สมาชิก", guild=TARGET_GUILD)
async def profile_board(interaction: discord.Interaction):
    if not can_announce(interaction):
        return await interaction.response.send_message("❌ เฉพาะ Organizer, Staff หรือผู้ดูแลเท่านั้น", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        channel, message = await ensure_profile_board(interaction.guild)
        await interaction.followup.send(f"✅ แผงโปรไฟล์พร้อมใช้งาน: {channel.mention}\n{message.jump_url}", ephemeral=True)
    except (discord.HTTPException, discord.Forbidden, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        traceback.print_exc()
        await interaction.followup.send(f"❌ สร้างแผงโปรไฟล์ไม่ได้: {type(exc).__name__}: {str(exc)[:220]}", ephemeral=True)


async def show_team_browse(interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID:
        return await interaction.response.send_message("ใช้ได้เฉพาะใน InveNOIR Chorus Battle", ephemeral=True)
    try:
        data = team_data_load()
        teams = [t for t in data["teams"] if t.get("status") == "recruiting"]
        teams.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return await interaction.response.send_message(f"❌ อ่านรายการทีมไม่ได้: {str(exc)[:160]}", ephemeral=True)
    if not teams:
        return await interaction.response.send_message("📭 ตอนนี้ยังไม่มีทีมเปิดรับสมาชิก", ephemeral=True)
    first_embed = team_embed(teams[0])
    first_embed.description = (str(teams[0].get("description", ""))[:3000] +
                               f"\n\n**ทีมที่ 1 จาก {len(teams)}**\nใช้ปุ่มก่อนหน้า/ถัดไปเพื่อดูทีมอื่น")
    first_embed.set_footer(text="INVENOIR • TEAM CARDS / PAGINATED BROWSER")
    await interaction.response.send_message(
        content="🔎 **ทีมที่กำลังเปิดรับสมาชิก** — ดูการ์ดทีมขนาดใหญ่และเลื่อนด้วยปุ่ม ไม่ต้องเลือกจาก Dropdown",
        embed=first_embed, view=TeamBrowseView(teams, owner_id=interaction.user.id), ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@client.tree.command(name="team_browse", description="ค้นหาทีมที่กำลังเปิดรับสมาชิก", guild=TARGET_GUILD)
async def team_browse(interaction: discord.Interaction):
    await show_team_browse(interaction)


@client.tree.command(name="team_applications", description="ดูคำขอเข้าทีมที่รอการตอบรับ", guild=TARGET_GUILD)
async def team_applications(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID:
        return await interaction.response.send_message("ใช้ได้เฉพาะในเซิร์ฟเวอร์ InveNOIR", ephemeral=True)
    try:
        data = team_data_load()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return await interaction.response.send_message(f"❌ อ่านคำขอไม่ได้: {str(exc)[:160]}", ephemeral=True)
    is_staff = interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator or any(
        r.name in MODERATORS for r in getattr(interaction.user, "roles", []))
    teams = [t for t in data["teams"] if int(t.get("owner_id", 0)) == interaction.user.id]
    allowed_team_ids = {int(t["thread_id"]) for t in teams}
    apps = [a for a in data["applications"] if a.get("status") == "pending"
            and (is_staff or int(a.get("team_thread_id", 0)) in allowed_team_ids)]
    if not apps:
        return await interaction.response.send_message("📭 ไม่มีคำขอที่รอพิจารณาอยู่", ephemeral=True)
    lines = []
    for app in apps[:20]:
        lines.append(f"• **#{app['id']}** — **{app.get('team_name','ทีม')}** — <@{app['applicant_id']}>\n"
                     f"  ตอบรับ/ปฏิเสธ: `/team_application_decide application_id:{app['id']} decision:accept` หรือ `decline`")
    await interaction.response.send_message("📨 **คำขอเข้าทีมที่รอพิจารณา**\n" + "\n".join(lines)[:1850], ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="team_application_decide", description="ตอบรับหรือปฏิเสธคำขอเข้าทีม", guild=TARGET_GUILD)
@app_commands.describe(application_id="เลข # จาก DM หรือ /team_applications", decision="accept หรือ decline")
async def team_application_decide(interaction: discord.Interaction, application_id: int, decision: Literal["accept", "decline"]):
    if not interaction.guild or interaction.guild.id != GUILD_ID:
        return await interaction.response.send_message("ใช้ได้เฉพาะในเซิร์ฟเวอร์ InveNOIR", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    result = await process_team_application_decision(
        interaction.guild, application_id, decision, interaction.user.id, allow_staff=True)
    await interaction.followup.send(result, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@client.tree.command(name="team_rooms_sync", description="สร้าง/ซิงก์ห้องส่วนตัวให้ทีมที่มีสมาชิกยืนยันแล้ว", guild=TARGET_GUILD)
async def team_rooms_sync(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID or not is_staff_or_admin(interaction.user):
        return await interaction.response.send_message("❌ เฉพาะ Organizer, Staff หรือ Administrator เท่านั้น", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await ensure_team_rooms_category(interaction.guild)
        data = team_data_load()
        teams = [dict(t) for t in data.get("teams", []) if t.get("accepted_members")]
        done, errors = [], []
        for team in teams:
            try:
                old_channel_id = int(team.get("team_chat_channel_id") or 0)
                channel = await ensure_private_team_channel(interaction.guild, team)
                if channel is not None:
                    done.append((team.get("team_name", "Team"), channel.jump_url))
                    # Notify the confirmed roster only when a new/replacement room was created.
                    if old_channel_id != channel.id:
                        ids = [int(team.get("owner_id", 0))] + [int(x) for x in team.get("accepted_members", [])]
                        for uid in dict.fromkeys(x for x in ids if x):
                            member = await team_fetch_member(interaction.guild, uid)
                            if member is not None:
                                try:
                                    await member.send(
                                        f"🔒 ห้องคุยส่วนตัวรวมของทีม **{team.get('team_name', 'Team')}** พร้อมแล้ว\n{channel.jump_url}",
                                        allowed_mentions=discord.AllowedMentions.none())
                                except (discord.Forbidden, discord.HTTPException):
                                    pass
                else:
                    errors.append(str(team.get("team_name", "Team")))
            except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                errors.append(f"{team.get('team_name', 'Team')}: {type(exc).__name__}")
        msg = f"🔒 ซิงก์ห้องทีมส่วนตัวแล้ว {len(done)}/{len(teams)} ทีม"
        if done:
            msg += "\n" + "\n".join(f"• **{name}** — {url}" for name, url in done[:8])
        if errors:
            msg += "\n⚠️ ตรวจสิทธิ์บอทในหมวด Team Rooms: " + "; ".join(errors[:6])
        if not teams:
            msg += "\nยังไม่มีทีมที่มีสมาชิกยืนยันแล้วให้ซิงก์"
        await interaction.followup.send(msg[:1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        await interaction.followup.send(f"❌ ซิงก์ห้องทีมไม่ได้: {type(exc).__name__}: {str(exc)[:220]}", ephemeral=True)


@client.tree.command(name="team_browse_check", description="ตรวจสอบสถานะระบบ Team Finder", guild=TARGET_GUILD)
async def team_browse_check(interaction: discord.Interaction):
    try:
        data = team_data_load()
        recruiting = sum(t.get("status") == "recruiting" for t in data["teams"])
        full = sum(t.get("status") == "full" for t in data["teams"])
        closed = sum(t.get("status") == "closed" for t in data["teams"])
        pending = sum(a.get("status") == "pending" for a in data["applications"])
        forum = team_finder_forum(interaction.guild) if interaction.guild else None
        private_category = team_rooms_category(interaction.guild) if interaction.guild else None
        await interaction.response.send_message(
            f"**InveNOIR Group Finder v16.0**\nGroup Finder (Forum/Text): {'พบแล้ว' if forum else 'ไม่พบ group-finder'}\n"
            f"🟢 เปิดรับ: {recruiting} • 🔴 เต็ม: {full} • ⚫ ปิด: {closed}\n"
            f"📨 คำขอ Group Finder รอพิจารณา: {pending}\n"
            f"🪪 โปรไฟล์: {len(data.get('profiles', []))} • ✉️ คำเชิญ: {sum(i.get('status') == 'pending' for i in data.get('invitations', []))}\n"
            f"🔒 Group Finder Team Rooms: {'พร้อม' if private_category else 'ยังไม่มี'}\n"
            "Official Team Registration: ปิดใช้งานแล้ว • ห้อง #registration ว่าง\n"
            "ไฟล์ข้อมูล: `team_finder_data.json`", ephemeral=True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        await interaction.response.send_message(f"❌ อ่านสถานะไม่ได้: {str(exc)[:180]}", ephemeral=True)


# v16: officially retire the old competition Team Registration commands.
# The #registration channel remains intentionally empty for organizers to use later.
for _retired_command in (
    "registration_panel", "team_registrations", "team_registration_sync", "my_team_registration",
):
    try:
        client.tree.remove_command(_retired_command, guild=TARGET_GUILD)
    except (KeyError, ValueError):
        pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        source = Path(__file__).read_text(encoding="utf-8")
        assert VERSION.startswith("v16.0-")
        assert len(ANNOUNCE_KIND_LABELS) == 5
        assert len(ROLE_CONFIG) == 10
        assert set(ROLE_GROUP_NAMES) == {n for n, _ in ROLE_CONFIG}
        assert set(ROLE_HOIST) == set(ROLE_GROUP_NAMES)
        assert len(SECTIONS) == 6 and sum(len(section[1]) for section in SECTIONS) == 26
        assert privacy_category_type("✧ Team Rooms 🔒") == "teamrooms"
        assert privacy_readonly("📝・registration")
        assert "INVENOIR_DATA_DIR" in source and 'DATA_DIR / "team_finder_data.json"' in source
        assert "class TeamBrowseView" in source and "discord.ui.Select" not in source[source.index("class TeamBrowseView"):source.index("class ProfileBrowseView")]
        assert "class ProfileBrowseView" in source and "discord.ui.Select" not in source[source.index("class ProfileBrowseView"):source.index("class ProfileSelectedView")]
        print("[InveNOIR] LOCAL CHECK OK: v16 Group Finder + members-only profiles + profile-based applications + acceptance-based private Team Chat + cloud storage")
        sys.exit(0)
    client.run(TOKEN)
