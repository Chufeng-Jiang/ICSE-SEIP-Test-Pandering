import json
import shutil
from pathlib import Path
from typing import Any


# ============================================================
# Configuration
# ============================================================

# 这是前一个脚本生成的输出目录。
# 本脚本会直接修改该目录下的所有 JSONL 文件。
JSONL_ROOT = Path(
	"/home/chufeng/Desktop/CSI/pte-pilot/"
	"dataset/open_swe_traces_unresolved_chunks_with_steps"
)

TRAJECTORY_FIELD = "trajectory"
STEP_FIELD = "step"
TARGET_STEP = 1
STEP_COUNT_FIELD = "trajectory_step_count"

# True：删除 step == 1 的整个 trajectory 消息对象。
# False：保留该消息对象，仅删除其中的 content 字段。
REMOVE_WHOLE_STEP_MESSAGE = True

CONTENT_FIELD = "content"

# 删除 step 1 后是否重新编号剩余消息。
# False：保留原编号，例如第一条剩余消息仍然是 step 2。
# True：重新编号为 step 1、step 2、step 3……
RENUMBER_REMAINING_STEPS = False

# 是否在首次修改前为每个 JSONL 创建 .bak 备份。
# 例如：chunk.jsonl -> chunk.jsonl.bak
CREATE_BACKUP = False
BACKUP_SUFFIX = ".bak"

# 每处理多少条记录打印一次进度；0 表示不打印中间进度。
PROGRESS_INTERVAL = 1_000


# ============================================================
# Process one sample
# ============================================================

def process_sample(
	sample: Any,
	file_path: Path,
	line_number: int,
) -> tuple[dict[str, Any], int, bool]:
	if not isinstance(sample, dict):
		raise ValueError(
			f"Invalid JSONL record.\n"
			f"File: {file_path}\n"
			f"Line: {line_number}\n"
			f"Expected an object, found: {type(sample).__name__}"
		)

	if TRAJECTORY_FIELD not in sample:
		raise ValueError(
			f"Missing {TRAJECTORY_FIELD!r} field.\n"
			f"File: {file_path}\n"
			f"Line: {line_number}\n"
			f"trajectory_id: {sample.get('trajectory_id')!r}"
		)

	trajectory = sample[TRAJECTORY_FIELD]

	if not isinstance(trajectory, list):
		raise ValueError(
			f"Invalid {TRAJECTORY_FIELD!r} field.\n"
			f"File: {file_path}\n"
			f"Line: {line_number}\n"
			f"trajectory_id: {sample.get('trajectory_id')!r}\n"
			f"Expected a list, found: {type(trajectory).__name__}"
		)

	processed_trajectory: list[dict[str, Any]] = []
	removed_count = 0
	changed = False

	for position, message in enumerate(trajectory):
		if not isinstance(message, dict):
			raise ValueError(
				f"Invalid trajectory message.\n"
				f"File: {file_path}\n"
				f"Line: {line_number}\n"
				f"Trajectory position: {position}\n"
				f"Expected an object, found: {type(message).__name__}"
			)

		if message.get(STEP_FIELD) == TARGET_STEP:
			if REMOVE_WHOLE_STEP_MESSAGE:
				removed_count += 1
				changed = True
				continue

			processed_message = dict(message)

			if CONTENT_FIELD in processed_message:
				del processed_message[CONTENT_FIELD]
				removed_count += 1
				changed = True

			processed_trajectory.append(processed_message)
			continue

		processed_trajectory.append(dict(message))

	if RENUMBER_REMAINING_STEPS:
		for new_step, message in enumerate(
			processed_trajectory,
			start=1,
		):
			if message.get(STEP_FIELD) != new_step:
				message[STEP_FIELD] = new_step
				changed = True

	processed_sample = dict(sample)
	processed_sample[TRAJECTORY_FIELD] = processed_trajectory

	# 前一个脚本默认添加了该字段。这里始终重新计算，避免数量不一致。
	new_step_count = len(processed_trajectory)

	if processed_sample.get(STEP_COUNT_FIELD) != new_step_count:
		processed_sample[STEP_COUNT_FIELD] = new_step_count
		changed = True

	return processed_sample, removed_count, changed


# ============================================================
# Process one JSONL file in place
# ============================================================

def process_jsonl_file(file_path: Path) -> dict[str, int]:
	temporary_file = file_path.with_name(file_path.name + ".tmp")
	backup_file = file_path.with_name(file_path.name + BACKUP_SUFFIX)

	if temporary_file.exists():
		temporary_file.unlink()

	if CREATE_BACKUP and not backup_file.exists():
		shutil.copy2(file_path, backup_file)

	record_count = 0
	changed_record_count = 0
	removed_step_count = 0
	blank_line_count = 0

	try:
		with (
			file_path.open("r", encoding="utf-8") as input_stream,
			temporary_file.open(
				"w",
				encoding="utf-8",
				newline="\n",
			) as output_stream,
		):
			for line_number, raw_line in enumerate(
				input_stream,
				start=1,
			):
				json_text = raw_line.strip()

				if not json_text:
					blank_line_count += 1
					output_stream.write("\n")
					continue

				try:
					sample = json.loads(json_text)
				except json.JSONDecodeError as error:
					raise ValueError(
						f"Invalid JSON.\n"
						f"File: {file_path}\n"
						f"Line: {line_number}\n"
						f"JSON error: {error}"
					) from error

				processed_sample, removed_count, changed = process_sample(
					sample=sample,
					file_path=file_path,
					line_number=line_number,
				)

				output_stream.write(
					json.dumps(
						processed_sample,
						ensure_ascii=False,
						separators=(",", ":"),
					)
				)
				output_stream.write("\n")

				record_count += 1
				removed_step_count += removed_count

				if changed:
					changed_record_count += 1

				if (
					PROGRESS_INTERVAL > 0
					and record_count % PROGRESS_INTERVAL == 0
				):
					print(
						f"    Processed {record_count:,} records; "
						f"removed {removed_step_count:,} target steps"
					)

		# 只有整份文件成功完成后，才原子替换原文件。
		temporary_file.replace(file_path)

	except Exception:
		if temporary_file.exists():
			temporary_file.unlink()
		raise

	return {
		"records": record_count,
		"changed_records": changed_record_count,
		"removed_steps": removed_step_count,
		"blank_lines": blank_line_count,
	}


# ============================================================
# Main
# ============================================================

def main() -> None:
	if not JSONL_ROOT.exists():
		raise FileNotFoundError(
			f"JSONL root does not exist:\n{JSONL_ROOT}"
		)

	if not JSONL_ROOT.is_dir():
		raise NotADirectoryError(
			f"JSONL root is not a directory:\n{JSONL_ROOT}"
		)

	jsonl_files = sorted(JSONL_ROOT.rglob("*.jsonl"))

	if not jsonl_files:
		raise RuntimeError(
			f"No JSONL files found under:\n{JSONL_ROOT}"
		)

	print("=" * 80)
	print("Removing step 1 from JSONL files in place")
	print("=" * 80)
	print(f"Root:                  {JSONL_ROOT.resolve()}")
	print(f"JSONL files:           {len(jsonl_files):,}")
	print(f"Target step:           {TARGET_STEP}")
	print(f"Remove whole message:  {REMOVE_WHOLE_STEP_MESSAGE}")
	print(f"Renumber steps:        {RENUMBER_REMAINING_STEPS}")
	print(f"Create backups:        {CREATE_BACKUP}")
	print()

	total_records = 0
	total_changed_records = 0
	total_removed_steps = 0
	total_blank_lines = 0

	for file_index, file_path in enumerate(jsonl_files, start=1):
		relative_path = file_path.relative_to(JSONL_ROOT)
		print(f"[{file_index:,}/{len(jsonl_files):,}] {relative_path}")

		statistics = process_jsonl_file(file_path)

		total_records += statistics["records"]
		total_changed_records += statistics["changed_records"]
		total_removed_steps += statistics["removed_steps"]
		total_blank_lines += statistics["blank_lines"]

		print(
			f"    Records: {statistics['records']:,}; "
			f"changed: {statistics['changed_records']:,}; "
			f"removed: {statistics['removed_steps']:,}"
		)

	print()
	print("=" * 80)
	print("Completed")
	print("=" * 80)
	print(f"Processed files:       {len(jsonl_files):,}")
	print(f"Processed records:     {total_records:,}")
	print(f"Changed records:       {total_changed_records:,}")
	print(f"Removed step entries:  {total_removed_steps:,}")
	print(f"Blank lines preserved: {total_blank_lines:,}")
	print(f"Modified in place:     {JSONL_ROOT.resolve()}")


if __name__ == "__main__":
	main()