import json
from pathlib import Path

from datasets import load_from_disk


# ============================
# CONFIG
# ============================

INPUT_DIR = Path(
	"./dataset/open_swe_traces/add_trajectory_id"
)

OUTPUT_JSONL = Path(
	"./dataset/SWE-agent-trajectories/unresolved_trajectories.jsonl"
)


# ============================
# MAIN
# ============================

def main():

	print(
		"Loading dataset from:",
		INPUT_DIR
	)


	dataset = load_from_disk(
		str(INPUT_DIR)
	)


	print(dataset)


	OUTPUT_JSONL.parent.mkdir(
		parents=True,
		exist_ok=True
	)


	total_count = 0
	unresolved_count = 0


	with OUTPUT_JSONL.open(
		"w",
		encoding="utf-8"
	) as output_file:

		for split_name, split_dataset in dataset.items():

			print(
				f"Processing split: {split_name}"
			)


			split_unresolved_count = 0


			for sample in split_dataset:

				total_count += 1


				# target == False 表示任务没有解决
				if sample.get("target") is not False:

					continue


				# trajectory_id 已经存在，直接保留
				record = dict(sample)

				# 标记原始 split
				record["dataset_split"] = split_name


				output_file.write(
					json.dumps(
						record,
						ensure_ascii=False
					)
					+ "\n"
				)


				unresolved_count += 1
				split_unresolved_count += 1


			print(
				f"{split_name} unresolved: "
				f"{split_unresolved_count}"
			)


	print(
		f"Total samples: {total_count}"
	)

	print(
		f"Unresolved samples: {unresolved_count}"
	)

	print(
		"Saved to:",
		OUTPUT_JSONL
	)


if __name__ == "__main__":
	main()