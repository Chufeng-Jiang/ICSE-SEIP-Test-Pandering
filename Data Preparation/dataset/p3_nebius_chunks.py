import json
from pathlib import Path


# ============================
# CONFIG
# ============================

INPUT_JSONL = Path(
	"./dataset/SWE-agent-trajectories/unresolved_trajectories.jsonl"
)

OUTPUT_DIR = Path(
	"./dataset/SWE-agent-trajectories/unresolved_chunks"
)

RECORDS_PER_FILE = 200


# ============================
# SAVE CHUNK
# ============================

def save_chunk(
	records,
	chunk_index
):

	output_path = OUTPUT_DIR / (
		f"unresolved_chunk_{chunk_index:04d}.jsonl"
	)


	with output_path.open(
		"w",
		encoding="utf-8"
	) as output_file:

		for record in records:

			output_file.write(
				json.dumps(
					record,
					ensure_ascii=False
				)
				+ "\n"
			)


	print(
		f"Saved {len(records)} records to: "
		f"{output_path}"
	)


# ============================
# MAIN
# ============================

def main():

	if not INPUT_JSONL.exists():

		raise FileNotFoundError(
			f"Input file not found: {INPUT_JSONL}"
		)


	OUTPUT_DIR.mkdir(
		parents=True,
		exist_ok=True
	)


	records = []
	chunk_index = 1
	total_records = 0


	with INPUT_JSONL.open(
		"r",
		encoding="utf-8"
	) as input_file:

		for line_number, line in enumerate(
			input_file,
			start=1
		):

			line = line.strip()


			# 忽略空行
			if not line:

				continue


			try:

				record = json.loads(line)

			except json.JSONDecodeError as error:

				raise ValueError(
					f"Invalid JSON at line "
					f"{line_number}: {error}"
				) from error


			records.append(record)
			total_records += 1


			if len(records) == RECORDS_PER_FILE:

				save_chunk(
					records=records,
					chunk_index=chunk_index
				)


				records = []
				chunk_index += 1


	# 保存最后不足 200 条的记录
	if records:

		save_chunk(
			records=records,
			chunk_index=chunk_index
		)


	total_files = (
		total_records + RECORDS_PER_FILE - 1
	) // RECORDS_PER_FILE


	print("\n============================")
	print(f"Total records: {total_records}")
	print(f"Records per file: {RECORDS_PER_FILE}")
	print(f"Total output files: {total_files}")
	print(f"Output directory: {OUTPUT_DIR}")
	print("============================")


if __name__ == "__main__":
	main()