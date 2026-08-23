from pathlib import Path

from datasets import load_dataset, DatasetDict


# ============================
# CONFIG
# ============================

DATASET_NAME = "nebius/SWE-agent-trajectories"

CACHE_DIR = "./dataset/SWE-agent-trajectories"

OUTPUT_DIR = (
	Path("./dataset/SWE-agent-trajectories")
	/ "add_trajectory_id"
)


# ============================
# ADD ID
# ============================

def add_trajectory_id(dataset):

	trajectory_ids = []


	for idx, instance_id in enumerate(
		dataset["instance_id"]
	):

		trajectory_ids.append(
			f"{instance_id}_{idx}"
		)


	# 如果之前已经存在 trajectory_id，
	# 先删除，避免 add_column 报错
	if "trajectory_id" in dataset.column_names:

		dataset = dataset.remove_columns(
			"trajectory_id"
		)


	return dataset.add_column(
		"trajectory_id",
		trajectory_ids
	)


# ============================
# MAIN
# ============================

def main():

	print("Loading dataset...")


	dataset = load_dataset(
		DATASET_NAME,
		cache_dir=CACHE_DIR
	)


	print(dataset)


	output = DatasetDict()


	for split in dataset:

		print(
			f"Processing {split}"
		)


		output[split] = add_trajectory_id(
			dataset[split]
		)


		print(
			output[split]
		)


		# 简单检查前几个 sample
		for idx in range(
			min(5, len(output[split]))
		):

			print(
				idx,
				output[split][idx]["trajectory_id"]
			)


	print(
		"Saving to:",
		OUTPUT_DIR
	)


	output.save_to_disk(
		str(OUTPUT_DIR)
	)


	print("Done!")


if __name__ == "__main__":
	main()