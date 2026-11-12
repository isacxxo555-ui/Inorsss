INVENOIR CHORUS BATTLE BOT v16.0
TEAM REGISTRATION + GROUP FINDER + CLOUD EDITION
================================================

จุดเปลี่ยนสำคัญของ v16
----------------------
แยกระบบ 2 อย่างออกจากกันอย่างชัดเจน:

1) GROUP FINDER — ใช้ค้นหาสมาชิกและรวมทีม
- โพสต์ประกาศทีมใน group-finder
- สมาชิกสร้างโปรไฟล์ ใส่นามแฝง/ทักษะ/ผลงาน
- ทีมเปิดรับสมาชิก ส่งคำขอ และเชิญสมาชิกได้
- หน้าค้นหาทีมและโปรไฟล์เป็นการ์ด Embed แบบหน้าต่างค้นหา มีปุ่มก่อนหน้า/ถัดไป/สมัครทีม/เชิญเข้าทีม ไม่ใช้ Dropdown
- ห้องทีมจาก Group Finder ยังอยู่ในหมวด Team Rooms แยกของตัวเอง

2) TEAM REGISTRATION — สมัครแข่งขันอย่างเป็นทางการเมื่อทีมพร้อมแล้ว
- ไม่ต้องสร้างโพสต์ใน Group Finder ก่อน
- หัวหน้าทีมกดปุ่มใน 📝・registration แล้วกรอกชื่อทีม, Discord ID หัวหน้าทีม,
  รายชื่อสมาชิก, ตำแหน่ง, Portfolio และคอนเซปต์ทีม
- กรอก Discord ID ของสมาชิกทุกคนเพื่อให้บอทตรวจว่ามีตัวตนในเซิร์ฟเวอร์จริง
- เมื่อส่งใบสมัครสำเร็จ บอทสร้างห้องแชทส่วนตัวให้สมาชิกตาม ID ทันที
- ใบสมัครถูกส่งเข้า 📨・team-registration-review ซึ่งเห็นได้เฉพาะ Organizer / Staff / Admin
- ห้องทีมจะอยู่ในหมวด ✧ Registered Teams 🔒 แยกจาก Team Rooms ของ Group Finder
- ทีมงานกดอนุมัติหรือไม่อนุมัติได้จากปุ่มบนใบสมัคร
- เมื่ออนุมัติ ห้องทีมเปิดใช้ต่อได้; เมื่อไม่อนุมัติ บอทล็อกห้องและเก็บประวัติไว้ให้ทีมงาน
- สมาชิกตรวจสอบสถานะได้จากปุ่มใน registration หรือคำสั่ง /my_team_registration

วิธีกรอกใบสมัครทีม
------------------
ในห้อง 📝・registration กดปุ่ม “ลงทะเบียนทีมเข้าแข่งขัน”

1. ชื่อทีม: ใส่ชื่อที่ต้องการใช้สมัคร
2. Discord ID ของหัวหน้าทีม: ถ้าหัวหน้าทีมเป็นคนกดส่ง ระบบจะเติม ID ของผู้ส่งให้เอง (แก้ไขได้)
3. รายชื่อสมาชิก + ตำแหน่ง: ต้องใส่หัวหน้าทีมรวมด้วย 1 คนต่อ 1 บรรทัด ตามรูปแบบนี้
   Discord ID | ชื่อในทีม | ตำแหน่ง
   12345678901234567 | Bom | Vocalist
   23456789012345678 | Alex | Mixer
4. ผลงานสมาชิก (ไม่บังคับ): 1 ลิงก์ต่อ 1 บรรทัด โดยระบุ ID เจ้าของผลงาน
   Discord ID | https://ลิงก์ผลงาน
   12345678901234567 | https://example.com/bom
   23456789012345678 | https://example.com/alex
5. คอนเซปต์ / แนะนำทีม: อธิบายแนวคิดหรือสิ่งที่ทีมจะนำเสนอ

ข้อกำหนด:
- สูงสุด 20 คนต่อทีม
- ทุก ID ต้องเป็นสมาชิกที่อยู่ใน Discord Server นี้ และไม่ใช่บัญชีบอท
- หัวหน้าทีมต้องเป็นผู้ส่งใบสมัครเอง หรือให้ Organizer/Staff ส่งแทน
- ใส่ ID ซ้ำไม่ได้ และสมาชิกหนึ่งคนอยู่ในใบสมัครทีมที่ยังดำเนินการอยู่ได้ครั้งละทีมเดียว
- Portfolio ต้องเป็นลิงก์ http:// หรือ https://; สูงสุด 5 ลิงก์ต่อคน
- เปิด Developer Mode ใน Discord: User Settings > Advanced > Developer Mode
  จากนั้นคลิกขวาที่สมาชิก > Copy User ID

คำสั่งที่เพิ่มใน v16
--------------------
- /team_board — สร้าง/อัปเดต Group Finder, โปรไฟล์ และแผง Team Registration
- /registration_panel — สร้าง/อัปเดตแผงสมัครแข่งขันในห้อง registration
- /my_team_registration — สมาชิกตรวจสอบสถานะใบสมัครของตัวเอง
- /team_registrations — Organizer/Staff/Admin ดูใบสมัครที่รอตรวจ
- /team_registration_sync — Organizer/Staff/Admin ซ่อมห้องทีมและโพสต์ตรวจใบสมัคร
- /team_browse_check — ตรวจสอบสถานะระบบ Team Finder และ Team Registration
- /team_browse — ค้นหาทีมที่เปิดรับสมาชิก
- /team_rooms_sync — ซิงก์ห้องส่วนตัวของทีมที่รวมสมาชิกผ่าน Group Finder

การติดตั้งบน Windows
--------------------
1. ปิดบอทเวอร์ชันเดิมก่อน (อย่าเปิดสองเวอร์ชันพร้อมกัน)
2. แตก ZIP v16 ลงในโฟลเดอร์ใหม่ แยกจาก v12.2/v13
3. คัดลอกไฟล์ .env จากเวอร์ชันเดิมมาไว้ในโฟลเดอร์ v16
   ถ้าไม่มีไฟล์เดิม ให้คัดลอก ENV_EXAMPLE.txt แล้วเปลี่ยนชื่อเป็น .env จากนั้นใส่ Bot Token และ Server ID
   (ไฟล์ .env.example เป็นไฟล์ซ่อนในบางโปรแกรมแตก ZIP; ENV_EXAMPLE.txt เป็นสำเนาที่มองเห็นได้)
   ห้ามส่ง .env หรือ Bot Token ให้ใคร
4. คัดลอกข้อมูลที่ต้องการเก็บจากเวอร์ชันเดิม เช่น:
   - team_finder_data.json
   - announcements_jobs.json
   - privacy_backup_original.json และ privacy_backup*.json (ถ้ามี)
5. เปิด START_V16.bat (ตัวติดตั้งจะติดตั้ง discord.py และตรวจไฟล์ให้อัตโนมัติ)
6. เมื่อบอทขึ้น READY ให้ใช้ /team_browse_check ตรวจสอบ
7. ใช้ /team_board หนึ่งครั้งเพื่อสร้าง/อัปเดตแผง Group Finder, โปรไฟล์ และ Team Registration
8. หากต้องการอัปเดตแผงสมัครอย่างเดียว ใช้ /registration_panel
9. หากห้องทีมสมัครแข่งขันสร้างไม่สำเร็จ ให้ทีมงานใช้ /team_registration_sync

การย้ายห้องตรวจใบสมัคร
----------------------
- ถ้าพบห้องเก่า 📨・full-team-applications จากระบบ waitlist รุ่นก่อน
  v16 จะพยายามเปลี่ยนชื่อและนำมาใช้เป็น 📨・team-registration-review โดยไม่ลบข้อความเดิม
- ห้องทีมสมัครแข่งขันใหม่จะอยู่ในหมวด ✧ Registered Teams 🔒
- ห้องทีมส่วนตัวที่มาจาก Group Finder ยังคงอยู่ในหมวด ✧ Team Rooms 🔒
- /privacy_apply จะไม่ไปเขียนทับสิทธิ์เฉพาะสมาชิกของห้องส่วนตัวทั้งสองหมวด

ทำให้บอทออนไลน์ 24/7 ด้วย Railway
----------------------------------
หมายเหตุ: การรันบน Windows จะหยุดเมื่อปิดคอม/ปิดโปรแกรม/เครื่อง Sleep
หากต้องการออนไลน์ตลอด ให้รันบน Cloud/VPS

Railway (มีค่าใช้จ่าย):
- แผน Hobby มีค่าขั้นต่ำ $5/เดือน และเครดิตการใช้งาน $5; หากใช้เกินจะคิดเพิ่มตามทรัพยากร
- Volume บน Hobby มีพื้นที่เริ่มต้น 5GB และคิดค่าพื้นที่ตามปริมาณที่ใช้จริง
1. สร้าง Private GitHub repository
2. อัปโหลดไฟล์ v16 ขึ้น GitHub โดยห้ามใส่ .env, team_finder_data.json หรือข้อมูลส่วนตัว
3. สร้าง Railway Project จาก GitHub repository; ระบบจะใช้ Dockerfile ในโฟลเดอร์นี้
4. ตั้ง Variables:
   DISCORD_BOT_TOKEN=โทเคนบอท
   DISCORD_GUILD_ID=ไอดีเซิร์ฟเวอร์
   INVENOIR_DATA_DIR=/data
5. เพิ่ม Persistent Volume และตั้ง Mount Path เป็น /data
6. Settings > Deploy ตั้ง Restart Policy เป็น ALWAYS
7. Deploy และดู Logs จนเห็น [InveNOIR] READY
8. หยุดบอทบน Windows หลัง Cloud พร้อมทำงานแล้ว

ข้อมูลสำคัญ:
- ห้ามเปิดบอทบน Windows และ Railway พร้อมกัน เพราะอาจตอบ interaction ซ้ำหรือเขียน JSON แข่งกัน
- หากย้ายข้อมูลขึ้น Railway ให้ใช้ Railway CLI และอัปโหลด JSON เข้า Volume ที่ /data
- อย่า commit .env, Bot Token, team_finder_data.json หรือไฟล์ที่มีข้อมูลสมาชิกลง GitHub

ไฟล์ข้อมูลที่เก็บใน INVENOIR_DATA_DIR
------------------------------------
- team_finder_data.json: Group Finder, โปรไฟล์, คำเชิญ, ใบสมัครแข่งขัน, รายชื่อสมาชิก และ channel IDs
- announcements_jobs.json: ประกาศที่ตั้งเวลาไว้
- privacy_backup*.json: สำรอง permission
- deleted_team_finder_manifest_*.json: manifest สำหรับการลบห้องเก่า

สิทธิ์บอทที่จำเป็น
------------------
- Manage Channels, View Channels, Send Messages, Read Message History, Embed Links
- Manage Roles สำหรับระบบเลือกยศ (ยศบอทต้องอยู่สูงกว่ายศสมาชิก)
- Group Finder Forum: Create Posts; หรือ Text Channel: Create Public Threads + Send Messages in Threads
- Staff Only: ดู/ส่งข้อความใน team-registration-review
- Registered Teams และ Team Rooms: Manage Channels และจัดการ Permission Overwrites
- การแจ้งเตือน DM อาจส่งไม่ได้ถ้าสมาชิกปิด Direct Messages แต่สมาชิกยังเข้าห้องทีมได้ตามสิทธิ์

ข้อจำกัดการทดสอบ
----------------
ตรวจ syntax, parser/ID validation, command names และ static checks ในเครื่องแล้ว
แต่ยังไม่ได้เชื่อมต่อ Discord จริงหรือ Deploy Railway แทนผู้ใช้


==============================
อัปเดต v16 — Group Finder & Member Profile
==============================
- ปิดระบบ Official Team Registration และนำคำสั่ง registration_panel, team_registrations, team_registration_sync, my_team_registration ออกจากคำสั่งบอท
- ห้อง #registration คงอยู่ แต่บอทจะไม่สร้างแผงสมัครหรือโพสต์ใบสมัครลงห้องนี้
- Group Finder และ Member Profile ยังคงใช้งานต่อ พร้อมเก็บไฟล์ข้อมูลเดิม team_finder_data.json
- Member Profile จำกัดสิทธิ์มองเห็นเฉพาะ Organizer/Staff และสายงานแข่งขัน: Team Leader, Vocalist, VTuber, Mixer, Illustrator, PV Editor (ไม่รวม Audience/Judge)
- การสมัครทีมใช้ข้อมูลจาก Member Profile ที่บันทึกไว้ พร้อมข้อความแนะนำตัวเพิ่มเติม
- Team Chat ส่วนตัวจะถูกสร้าง/เปิดให้หลังหัวหน้าทีมกดยอมรับเท่านั้น
- Safety: ป้องกันการ mention โดยไม่จำเป็น, ตรวจ URL portfolio, จำกัดการสมัครซ้ำ/สถานะใบสมัคร และจำกัดการตัดสินใจให้เจ้าของทีม/Staff ตามระบบเดิม

วิธีเริ่มใช้งาน
1) แตก ZIP ลงโฟลเดอร์ใหม่ อย่าทับโฟลเดอร์ v15 เดิม
2) คัดลอกไฟล์ .env เดิมของคุณมาไว้ในโฟลเดอร์ v16 (อย่าส่งไฟล์นี้ให้ใคร)
3) คัดลอก team_finder_data.json จากโฟลเดอร์ v15 มาไว้ในโฟลเดอร์ v16 เพื่อรักษาทีม/โปรไฟล์/คำขอเดิม
4) รัน START_V16.bat
5) ใน Discord ใช้ /team_board เพื่อสร้างหรืออัปเดต Group Finder Dashboard และ Member Profile panel
6) สมาชิกใช้ปุ่มสร้าง/แก้ไขโปรไฟล์ จากนั้นใช้ Find a Team หรือเปิดประกาศทีมเพื่อสมัคร
7) Team Leader ใช้ /team_applications หรือปุ่มใน DM/โพสต์เพื่อพิจารณา Accept/Decline; เมื่อ Accept ระบบจะจัดการ Team Chat ตาม flow เดิม
8) ใช้ /team_browse_check เพื่อตรวจสถานะ Group Finder

หมายเหตุสำคัญ
- v16 ไม่ลบข้อความหรือห้องเดิมใน Discord โดยอัตโนมัติ เพื่อป้องกันข้อมูลสูญหาย
- หากห้องเก่า team-registration-review หรือหมวด Registered Teams มีอยู่แล้ว จะไม่ถูกลบโดยบอท; สามารถลบเองภายหลังเมื่อแน่ใจว่าไม่ต้องใช้ประวัติเดิม
- คำสั่ง Team Registration ถูกถอดจากเมนู sync ของบอท แต่โค้ดส่วนเก่าบางส่วนยังคงอยู่ภายในไฟล์เพื่อหลีกเลี่ยงการทำลายข้อมูลประวัติเดิมโดยไม่จำเป็น
- แนะนำให้สำรอง team_finder_data.json ก่อนอัปเดตทุกครั้ง
