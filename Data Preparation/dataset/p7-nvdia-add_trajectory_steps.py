import json
import shutil
from pathlib import Path
from typing import Any


# ============================================================
# Configuration
# ============================================================

# 原始 unresolved chunks 目录
INPUT_ROOT = Path(
	"/home/chufeng/Desktop/CSI/pte-pilot/"
	"dataset/open_swe_traces_unresolved_chunks"
)

# 添加 step 后保存的新目录
OUTPUT_ROOT = Path(
	"/home/chufeng/Desktop/CSI/pte-pilot/"
	"dataset/open_swe_traces_unresolved_chunks_with_steps"
)

# 每个 trajectory 消息中的步骤字段名称
STEP_FIELD = "step"

# 步骤从 1 开始：
# 1 = system
# 2 = user
# 3 = assistant
# 4 = tool
# ...
STEP_START = 1

# 是否给 sample 顶层增加轨迹总步骤数字段：
#
# {
#     "trajectory_step_count": 23,
#     "trajectory": [...]
# }
#
# 默认开启。
ADD_TRAJECTORY_STEP_COUNT = True

STEP_COUNT_FIELD = "trajectory_step_count"

# 如果 trajectory 中已经存在 step 字段：
#
# True：重新编号并覆盖
# False：直接报错，防止意外覆盖
OVERWRITE_EXISTING_STEP = True

# 如果输出目录已经存在：
#
# True：先删除整个输出目录，然后重新生成
# False：直接报错
OVERWRITE_OUTPUT_ROOT = False

# 每处理多少条记录打印一次进度
PROGRESS_INTERVAL = 1_000


# ============================================================
# Annotate one trajectory
# ============================================================

def add_steps_to_trajectory(
	trajectory: list[Any],
	file_path: Path,
	line_number: int,
) -> list[dict[str, Any]]:

	annotated_trajectory: list[dict[str, Any]] = []

	for offset, message in enumerate(
		trajectory
	):

		step_number = (
			STEP_START
			+
			offset
		)

		if not isinstance(
			message,
			dict,
		):

			raise ValueError(
				f"Invalid trajectory message.\n"
				f"File: {file_path}\n"
				f"JSONL line: {line_number}\n"
				f"Trajectory position: {offset}\n"
				f"Expected a JSON object, but found: "
				f"{type(message).__name__}"
			)

		if (
			STEP_FIELD in message
			and
			not OVERWRITE_EXISTING_STEP
		):

			raise ValueError(
				f"Existing {STEP_FIELD!r} field found.\n"
				f"File: {file_path}\n"
				f"JSONL line: {line_number}\n"
				f"Trajectory position: {offset}\n"
				f"Existing value: "
				f"{message[STEP_FIELD]!r}"
			)

		# 将 step 放在每个消息对象的第一个字段。
		#
		# 排除原来的 step 字段，避免重复；当允许覆盖时，
		# 使用当前重新计算的步骤编号。
		annotated_message = {
			STEP_FIELD: step_number,
		}

		for key, value in message.items():

			if key == STEP_FIELD:
				continue

			annotated_message[key] = value

		annotated_trajectory.append(
			annotated_message
		)

	return annotated_trajectory


# ============================================================
# Process one sample
# ============================================================

def process_sample(
	sample: Any,
	file_path: Path,
	line_number: int,
) -> tuple[dict[str, Any], int]:

	if not isinstance(
		sample,
		dict,
	):

		raise ValueError(
			f"Invalid sample.\n"
			f"File: {file_path}\n"
			f"JSONL line: {line_number}\n"
			f"Expected a JSON object, but found: "
			f"{type(sample).__name__}"
		)

	if "trajectory" not in sample:

		raise ValueError(
			f"Missing trajectory field.\n"
			f"File: {file_path}\n"
			f"JSONL line: {line_number}\n"
			f"trajectory_id: "
			f"{sample.get('trajectory_id')!r}"
		)

	trajectory = sample["trajectory"]

	if not isinstance(
		trajectory,
		list,
	):

		raise ValueError(
			f"Invalid trajectory field.\n"
			f"File: {file_path}\n"
			f"JSONL line: {line_number}\n"
			f"trajectory_id: "
			f"{sample.get('trajectory_id')!r}\n"
			f"Expected a list, but found: "
			f"{type(trajectory).__name__}"
		)

	annotated_trajectory = add_steps_to_trajectory(
		trajectory=trajectory,
		file_path=file_path,
		line_number=line_number,
	)

	processed_sample = dict(
		sample
	)

	processed_sample["trajectory"] = (
		annotated_trajectory
	)

	if ADD_TRAJECTORY_STEP_COUNT:

		processed_sample[
			STEP_COUNT_FIELD
		] = len(
			annotated_trajectory
		)

	return (
		processed_sample,
		len(annotated_trajectory),
	)


# ============================================================
# Process one JSONL file
# ============================================================

def process_jsonl_file(
	input_file: Path,
	output_file: Path,
) -> dict[str, int]:

	output_file.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	temporary_output = output_file.with_name(
		output_file.name + ".tmp"
	)

	if temporary_output.exists():

		temporary_output.unlink()

	record_count = 0
	message_count = 0
	blank_line_count = 0
	minimum_steps: int | None = None
	maximum_steps: int | None = None

	try:

		with (
			input_file.open(
				"r",
				encoding="utf-8",
			) as input_stream,
			temporary_output.open(
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
					continue

				try:

					sample = json.loads(
						json_text
					)

				except json.JSONDecodeError as error:

					raise ValueError(
						f"Invalid JSON.\n"
						f"File: {input_file}\n"
						f"JSONL line: {line_number}\n"
						f"JSON error: {error}"
					) from error

				(
					processed_sample,
					trajectory_steps,
				) = process_sample(
					sample=sample,
					file_path=input_file,
					line_number=line_number,
				)

				# 每个 sample 仍然保存为 JSONL 中的一行。
				output_stream.write(
					json.dumps(
						processed_sample,
						ensure_ascii=False,
						separators=(",", ":"),
					)
				)

				output_stream.write(
					"\n"
				)

				record_count += 1
				message_count += trajectory_steps

				if minimum_steps is None:

					minimum_steps = (
						trajectory_steps
					)

					maximum_steps = (
						trajectory_steps
					)

				else:

					minimum_steps = min(
						minimum_steps,
						trajectory_steps,
					)

					maximum_steps = max(
						maximum_steps,
						trajectory_steps,
					)

		temporary_output.replace(
			output_file
		)

	except Exception:

		if temporary_output.exists():

			temporary_output.unlink()

		raise

	return {
		"records": record_count,
		"messages": message_count,
		"blank_lines": blank_line_count,
		"minimum_steps": (
			minimum_steps
			if minimum_steps is not None
			else 0
		),
		"maximum_steps": (
			maximum_steps
			if maximum_steps is not None
			else 0
		),
	}


# ============================================================
# Copy non-JSONL files
# ============================================================

def copy_non_jsonl_file(
	input_file: Path,
	output_file: Path,
) -> None:

	output_file.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	shutil.copy2(
		input_file,
		output_file,
	)


# ============================================================
# Validate paths
# ============================================================

def prepare_directories() -> None:

	if not INPUT_ROOT.exists():

		raise FileNotFoundError(
			f"Input directory does not exist:\n"
			f"{INPUT_ROOT}"
		)

	if not INPUT_ROOT.is_dir():

		raise NotADirectoryError(
			f"Input path is not a directory:\n"
			f"{INPUT_ROOT}"
		)

	if (
		INPUT_ROOT.resolve()
		==
		OUTPUT_ROOT.resolve()
	):

		raise ValueError(
			"Input and output directories must be different."
		)

	# 防止把输出目录放到输入目录内部，从而递归处理刚生成的文件。
	try:

		OUTPUT_ROOT.resolve().relative_to(
			INPUT_ROOT.resolve()
		)

	except ValueError:

		pass

	else:

		raise ValueError(
			"OUTPUT_ROOT cannot be inside INPUT_ROOT.\n"
			f"INPUT_ROOT:  {INPUT_ROOT.resolve()}\n"
			f"OUTPUT_ROOT: {OUTPUT_ROOT.resolve()}"
		)

	if OUTPUT_ROOT.exists():

		if not OVERWRITE_OUTPUT_ROOT:

			raise FileExistsError(
				f"Output directory already exists:\n"
				f"{OUTPUT_ROOT}\n\n"
				f"Delete it manually or set:\n"
				f"OVERWRITE_OUTPUT_ROOT = True"
			)

		shutil.rmtree(
			OUTPUT_ROOT
		)

	OUTPUT_ROOT.mkdir(
		parents=True,
		exist_ok=False,
	)


# ============================================================
# Main processing
# ============================================================

def annotate_all_files() -> None:

	prepare_directories()

	all_input_files = sorted(
		path
		for path in INPUT_ROOT.rglob("*")
		if path.is_file()
	)

	jsonl_files = [
		path
		for path in all_input_files
		if path.suffix.lower() == ".jsonl"
	]

	other_files = [
		path
		for path in all_input_files
		if path.suffix.lower() != ".jsonl"
	]

	if not jsonl_files:

		raise RuntimeError(
			f"No JSONL files were found under:\n"
			f"{INPUT_ROOT}"
		)

	print("=" * 80)
	print("Adding trajectory step numbers")
	print("=" * 80)
	print(
		f"Input root:     {INPUT_ROOT.resolve()}"
	)
	print(
		f"Output root:    {OUTPUT_ROOT.resolve()}"
	)
	print(
		f"JSONL files:    {len(jsonl_files):,}"
	)
	print(
		f"Other files:    {len(other_files):,}"
	)
	print(
		f"Step field:     {STEP_FIELD!r}"
	)
	print(
		f"Starting step:  {STEP_START}"
	)
	print()

	total_records = 0
	total_messages = 0
	total_blank_lines = 0

	global_minimum_steps: int | None = None
	global_maximum_steps: int | None = None

	file_statistics: list[dict[str, Any]] = []

	for file_index, input_file in enumerate(
		jsonl_files,
		start=1,
	):

		relative_path = input_file.relative_to(
			INPUT_ROOT
		)

		output_file = (
			OUTPUT_ROOT
			/
			relative_path
		)

		print(
			f"[{file_index:,}/{len(jsonl_files):,}] "
			f"{relative_path}"
		)

		statistics = process_jsonl_file(
			input_file=input_file,
			output_file=output_file,
		)

		total_records += statistics["records"]
		total_messages += statistics["messages"]
		total_blank_lines += statistics[
			"blank_lines"
		]

		if statistics["records"] > 0:

			if global_minimum_steps is None:

				global_minimum_steps = (
					statistics["minimum_steps"]
				)

				global_maximum_steps = (
					statistics["maximum_steps"]
				)

			else:

				global_minimum_steps = min(
					global_minimum_steps,
					statistics["minimum_steps"],
				)

				global_maximum_steps = max(
					global_maximum_steps,
					statistics["maximum_steps"],
				)

		file_statistics.append({
			"relative_path": str(
				relative_path
			),
			"records": statistics["records"],
			"trajectory_messages": (
				statistics["messages"]
			),
			"blank_lines": (
				statistics["blank_lines"]
			),
			"minimum_steps": (
				statistics["minimum_steps"]
			),
			"maximum_steps": (
				statistics["maximum_steps"]
			),
		})

		print(
			f"    Records: {statistics['records']:,}, "
			f"messages: {statistics['messages']:,}, "
			f"steps: "
			f"{statistics['minimum_steps']}–"
			f"{statistics['maximum_steps']}"
		)

	# 复制 statistics.json、statistics.csv 等非 JSONL 文件，
	# 保持原始目录结构。
	for input_file in other_files:

		relative_path = input_file.relative_to(
			INPUT_ROOT
		)

		output_file = (
			OUTPUT_ROOT
			/
			relative_path
		)

		copy_non_jsonl_file(
			input_file=input_file,
			output_file=output_file,
		)

	# 生成本次处理的独立统计文件。
	summary = {
		"input_root": str(
			INPUT_ROOT.resolve()
		),
		"output_root": str(
			OUTPUT_ROOT.resolve()
		),
		"step_field": STEP_FIELD,
		"step_start": STEP_START,
		"add_trajectory_step_count": (
			ADD_TRAJECTORY_STEP_COUNT
		),
		"step_count_field": (
			STEP_COUNT_FIELD
			if ADD_TRAJECTORY_STEP_COUNT
			else None
		),
		"jsonl_file_count": len(
			jsonl_files
		),
		"copied_non_jsonl_file_count": len(
			other_files
		),
		"total_records": total_records,
		"total_trajectory_messages": (
			total_messages
		),
		"total_blank_lines": (
			total_blank_lines
		),
		"minimum_trajectory_steps": (
			global_minimum_steps
			if global_minimum_steps is not None
			else 0
		),
		"maximum_trajectory_steps": (
			global_maximum_steps
			if global_maximum_steps is not None
			else 0
		),
		"files": file_statistics,
	}

	summary_file = (
		OUTPUT_ROOT
		/
		"step_annotation_statistics.json"
	)

	with summary_file.open(
		"w",
		encoding="utf-8",
	) as summary_stream:

		json.dump(
			summary,
			summary_stream,
			ensure_ascii=False,
			indent=2,
		)

		summary_stream.write(
			"\n"
		)

	print()
	print("=" * 80)
	print("Step annotation completed")
	print("=" * 80)
	print(
		f"Processed JSONL files:       "
		f"{len(jsonl_files):,}"
	)
	print(
		f"Processed samples:           "
		f"{total_records:,}"
	)
	print(
		f"Annotated trajectory items:  "
		f"{total_messages:,}"
	)
	print(
		f"Blank lines skipped:         "
		f"{total_blank_lines:,}"
	)
	print(
		f"Minimum steps per sample:    "
		f"{global_minimum_steps}"
	)
	print(
		f"Maximum steps per sample:    "
		f"{global_maximum_steps}"
	)
	print(
		f"Output directory:            "
		f"{OUTPUT_ROOT.resolve()}"
	)
	print(
		f"Statistics file:             "
		f"{summary_file.resolve()}"
	)


# ============================================================
# Entry point
# ============================================================

def main() -> None:

	annotate_all_files()


if __name__ == "__main__":
	main()