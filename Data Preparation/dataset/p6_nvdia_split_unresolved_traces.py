import argparse
import csv
import json
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from datasets import Dataset, DatasetDict, load_from_disk
from tqdm import tqdm


# ============================================================
# JSON serialization
# ============================================================

def json_default(value: Any) -> Any:
	"""
	Handle NumPy, Arrow, datetime, Path, bytes, and similar values
	that are not directly serializable by json.dumps().
	"""

	if hasattr(value, "item"):
		try:
			return value.item()
		except (ValueError, TypeError):
			pass

	if hasattr(value, "tolist"):
		try:
			return value.tolist()
		except (ValueError, TypeError):
			pass

	if isinstance(value, (datetime, date)):
		return value.isoformat()

	if isinstance(value, Path):
		return str(value)

	if isinstance(value, bytes):
		return value.decode(
			"utf-8",
			errors="replace",
		)

	raise TypeError(
		f"Object of type {type(value).__name__} "
		"is not JSON serializable"
	)


def normalize_scalar(value: Any) -> Any:
	"""
	Convert NumPy/Arrow scalar values into native Python scalars.
	"""

	if hasattr(value, "item"):
		try:
			return value.item()
		except (ValueError, TypeError):
			pass

	return value


def resolved_value_key(value: Any) -> str:
	"""
	Convert a resolved value into a readable statistics key.
	"""

	value = normalize_scalar(value)

	if value is None:
		return "null"

	return str(value)


# ============================================================
# File output
# ============================================================

def write_json(
	data: dict,
	output_path: Path,
) -> None:

	output_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	with output_path.open(
		"w",
		encoding="utf-8",
	) as file:

		json.dump(
			data,
			file,
			ensure_ascii=False,
			indent=2,
			default=json_default,
		)

		file.write("\n")


def write_jsonl_chunk(
	rows: list[dict],
	output_path: Path,
) -> None:
	"""
	Write one chunk atomically.

	The temporary file prevents an interrupted run from leaving behind
	a JSONL file that appears complete but is only partially written.
	"""

	output_path.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	temp_path = output_path.with_name(
		output_path.name + ".tmp"
	)

	with temp_path.open(
		"w",
		encoding="utf-8",
	) as file:

		for row in rows:

			file.write(
				json.dumps(
					row,
					ensure_ascii=False,
					default=json_default,
				)
			)

			file.write("\n")

	temp_path.replace(output_path)


# ============================================================
# Dataset processing
# ============================================================

def process_split(
	dataset: Dataset,
	output_directory: Path,
	chunk_size: int,
	filename_prefix: str,
	progress_description: str,
) -> dict:

	if "resolved" not in dataset.column_names:

		raise KeyError(
			f'Dataset "{progress_description}" does not contain '
			'a "resolved" column. '
			f"Available columns: {dataset.column_names}"
		)

	resolved_counts: Counter[str] = Counter()

	selected_count = 0
	chunk_count = 0
	buffer: list[dict] = []

	progress_bar = tqdm(
		dataset,
		total=len(dataset),
		desc=progress_description,
		unit="sample",
	)

	for sample in progress_bar:

		resolved_value = normalize_scalar(
			sample["resolved"]
		)

		resolved_counts[
			resolved_value_key(resolved_value)
		] += 1

		# Requirement:
		# Keep resolved == 0, resolved == -1,
		# and any other value not equal to 1.
		if resolved_value == 1:
			continue

		buffer.append(sample)
		selected_count += 1

		if len(buffer) >= chunk_size:

			chunk_count += 1

			chunk_path = (
				output_directory
				/
				f"{filename_prefix}"
				f"unresolved_chunk_{chunk_count:04d}.jsonl"
			)

			write_jsonl_chunk(
				buffer,
				chunk_path,
			)

			buffer.clear()

			progress_bar.set_postfix(
				selected=selected_count,
				chunks=chunk_count,
			)

	# Write the final incomplete chunk.
	if buffer:

		chunk_count += 1

		chunk_path = (
			output_directory
			/
			f"{filename_prefix}"
			f"unresolved_chunk_{chunk_count:04d}.jsonl"
		)

		write_jsonl_chunk(
			buffer,
			chunk_path,
		)

		buffer.clear()

	return {
		"total_samples": len(dataset),
		"selected_samples": selected_count,
		"excluded_resolved_1_samples": (
			len(dataset) - selected_count
		),
		"chunks_written": chunk_count,
		"chunk_size": chunk_size,
		"resolved_counts": dict(
			sorted(
				resolved_counts.items(),
				key=lambda item: item[0],
			)
		),
	}


def process_model_dataset(
	source_directory: Path,
	output_directory: Path,
	agent_name: str,
	model_name: str,
	chunk_size: int,
) -> dict:

	loaded_dataset = load_from_disk(
		str(source_directory)
	)

	output_directory.mkdir(
		parents=True,
		exist_ok=True,
	)

	split_statistics = []
	total_resolved_counts: Counter[str] = Counter()

	total_samples = 0
	total_selected_samples = 0
	total_chunks = 0

	if isinstance(loaded_dataset, DatasetDict):

		dataset_type = "DatasetDict"
		split_items = list(
			loaded_dataset.items()
		)

	else:

		dataset_type = "Dataset"
		split_items = [
			("data", loaded_dataset)
		]

	for split_name, split_dataset in split_items:

		if not isinstance(split_dataset, Dataset):

			raise TypeError(
				f"Unsupported split type in "
				f"{source_directory}: "
				f"{type(split_dataset).__name__}"
			)

		# DatasetDict files receive a split prefix so that
		# train/test/validation chunks cannot overwrite each other.
		if isinstance(loaded_dataset, DatasetDict):

			filename_prefix = (
				f"{split_name}_"
			)

		else:

			filename_prefix = ""

		progress_description = (
			f"{agent_name}/{model_name}"
		)

		if isinstance(loaded_dataset, DatasetDict):

			progress_description += (
				f"/{split_name}"
			)

		current_statistics = process_split(
			dataset=split_dataset,
			output_directory=output_directory,
			chunk_size=chunk_size,
			filename_prefix=filename_prefix,
			progress_description=progress_description,
		)

		current_statistics["split"] = split_name

		split_statistics.append(
			current_statistics
		)

		total_samples += (
			current_statistics["total_samples"]
		)

		total_selected_samples += (
			current_statistics["selected_samples"]
		)

		total_chunks += (
			current_statistics["chunks_written"]
		)

		total_resolved_counts.update(
			current_statistics["resolved_counts"]
		)

	model_statistics = {
		"agent": agent_name,
		"model": model_name,
		"dataset_type": dataset_type,
		"source_path": str(
			source_directory.resolve()
		),
		"output_path": str(
			output_directory.resolve()
		),
		"selection_condition": "resolved != 1",
		"chunk_size": chunk_size,
		"splits": split_statistics,
		"totals": {
			"total_samples": total_samples,
			"selected_samples": (
				total_selected_samples
			),
			"excluded_resolved_1_samples": (
				total_samples
				-
				total_selected_samples
			),
			"chunks_written": total_chunks,
			"resolved_counts": dict(
				sorted(
					total_resolved_counts.items(),
					key=lambda item: item[0],
				)
			),
		},
	}

	write_json(
		model_statistics,
		output_directory / "statistics.json",
	)

	return model_statistics


# ============================================================
# Global statistics
# ============================================================

def build_global_statistics(
	input_root: Path,
	output_root: Path,
	model_statistics: list[dict],
	errors: list[dict],
	chunk_size: int,
) -> dict:

	total_resolved_counts: Counter[str] = Counter()

	total_samples = 0
	total_selected_samples = 0
	total_chunks = 0

	for model_result in model_statistics:

		totals = model_result["totals"]

		total_samples += (
			totals["total_samples"]
		)

		total_selected_samples += (
			totals["selected_samples"]
		)

		total_chunks += (
			totals["chunks_written"]
		)

		total_resolved_counts.update(
			totals["resolved_counts"]
		)

	return {
		"input_root": str(
			input_root.resolve()
		),
		"output_root": str(
			output_root.resolve()
		),
		"selection_condition": "resolved != 1",
		"chunk_size": chunk_size,
		"processed_model_count": len(
			model_statistics
		),
		"error_count": len(errors),
		"totals": {
			"total_samples": total_samples,
			"selected_samples": (
				total_selected_samples
			),
			"excluded_resolved_1_samples": (
				total_samples
				-
				total_selected_samples
			),
			"chunks_written": total_chunks,
			"resolved_counts": dict(
				sorted(
					total_resolved_counts.items(),
					key=lambda item: item[0],
				)
			),
		},
		"models": model_statistics,
		"errors": errors,
	}


def write_statistics_csv(
	model_statistics: list[dict],
	output_path: Path,
) -> None:

	fieldnames = [
		"agent",
		"model",
		"dataset_type",
		"split",
		"source_path",
		"output_path",
		"total_samples",
		"selected_samples",
		"excluded_resolved_1_samples",
		"chunks_written",
		"chunk_size",
		"resolved_counts",
	]

	with output_path.open(
		"w",
		encoding="utf-8",
		newline="",
	) as file:

		writer = csv.DictWriter(
			file,
			fieldnames=fieldnames,
		)

		writer.writeheader()

		for model_result in model_statistics:

			for split_result in model_result["splits"]:

				writer.writerow({
					"agent": (
						model_result["agent"]
					),
					"model": (
						model_result["model"]
					),
					"dataset_type": (
						model_result["dataset_type"]
					),
					"split": (
						split_result["split"]
					),
					"source_path": (
						model_result["source_path"]
					),
					"output_path": (
						model_result["output_path"]
					),
					"total_samples": (
						split_result[
							"total_samples"
						]
					),
					"selected_samples": (
						split_result[
							"selected_samples"
						]
					),
					"excluded_resolved_1_samples": (
						split_result[
							"excluded_resolved_1_samples"
						]
					),
					"chunks_written": (
						split_result[
							"chunks_written"
						]
					),
					"chunk_size": (
						split_result[
							"chunk_size"
						]
					),
					"resolved_counts": json.dumps(
						split_result[
							"resolved_counts"
						],
						ensure_ascii=False,
						sort_keys=True,
					),
				})


# ============================================================
# Path validation
# ============================================================

def validate_paths(
	input_root: Path,
	output_root: Path,
) -> None:

	input_resolved = input_root.resolve()
	output_resolved = output_root.resolve()

	if not input_resolved.exists():

		raise FileNotFoundError(
			f"Input root does not exist: "
			f"{input_resolved}"
		)

	if not input_resolved.is_dir():

		raise NotADirectoryError(
			f"Input root is not a directory: "
			f"{input_resolved}"
		)

	# Prevent accidental deletion or recursive processing.
	if (
		input_resolved == output_resolved
		or
		input_resolved in output_resolved.parents
		or
		output_resolved in input_resolved.parents
	):

		raise ValueError(
			"Input and output directories must be "
			"separate sibling directories.\n"
			f"Input:  {input_resolved}\n"
			f"Output: {output_resolved}"
		)


# ============================================================
# Main
# ============================================================

def parse_arguments() -> argparse.Namespace:

	parser = argparse.ArgumentParser(
		description=(
			"Extract samples whose resolved value is not 1 "
			"from local NVIDIA Open-SWE trace datasets."
		)
	)

	parser.add_argument(
		"--input-root",
		type=Path,
		default=Path(
			"./dataset/open_swe_traces"
		),
		help=(
			"Root directory containing "
			"<agent>/<model> dataset directories."
		),
	)

	parser.add_argument(
		"--output-root",
		type=Path,
		default=None,
		help=(
			"Output directory. By default, a sibling directory "
			"named open_swe_traces_unresolved_chunks is used."
		),
	)

	parser.add_argument(
		"--chunk-size",
		type=int,
		default=200,
		help=(
			"Maximum number of samples in each JSONL file."
		),
	)

	parser.add_argument(
		"--overwrite",
		action="store_true",
		help=(
			"Delete the existing output directory before processing."
		),
	)

	return parser.parse_args()


def main() -> None:

	args = parse_arguments()

	input_root: Path = args.input_root

	if args.output_root is None:

		output_root = (
			input_root.parent
			/
			f"{input_root.name}"
			f"_unresolved_chunks"
		)

	else:

		output_root = args.output_root

	if args.chunk_size <= 0:

		raise ValueError(
			"--chunk-size must be greater than 0"
		)

	validate_paths(
		input_root,
		output_root,
	)

	if output_root.exists():

		if not args.overwrite:

			raise FileExistsError(
				f"Output directory already exists:\n"
				f"{output_root.resolve()}\n\n"
				"Use --overwrite to replace it."
			)

		shutil.rmtree(output_root)

	output_root.mkdir(
		parents=True,
		exist_ok=True,
	)

	model_statistics: list[dict] = []
	errors: list[dict] = []

	agent_directories = sorted(
		path
		for path in input_root.iterdir()
		if path.is_dir()
	)

	if not agent_directories:

		raise RuntimeError(
			f"No agent directories found under "
			f"{input_root.resolve()}"
		)

	for agent_directory in agent_directories:

		agent_name = agent_directory.name

		model_directories = sorted(
			path
			for path in agent_directory.iterdir()
			if path.is_dir()
		)

		for model_directory in model_directories:

			model_name = model_directory.name

			model_output_directory = (
				output_root
				/
				agent_name
				/
				model_name
			)

			print()
			print("=" * 70)
			print(
				f"Processing: "
				f"{agent_name}/{model_name}"
			)
			print(
				f"Source: {model_directory}"
			)
			print(
				f"Output: {model_output_directory}"
			)
			print("=" * 70)

			try:

				current_statistics = (
					process_model_dataset(
						source_directory=(
							model_directory
						),
						output_directory=(
							model_output_directory
						),
						agent_name=agent_name,
						model_name=model_name,
						chunk_size=(
							args.chunk_size
						),
					)
				)

				model_statistics.append(
					current_statistics
				)

			except Exception as error:

				error_record = {
					"agent": agent_name,
					"model": model_name,
					"source_path": str(
						model_directory.resolve()
					),
					"error_type": (
						type(error).__name__
					),
					"error": str(error),
				}

				errors.append(error_record)

				print(
					f"ERROR: "
					f"{agent_name}/{model_name}: "
					f"{type(error).__name__}: "
					f"{error}"
				)

	global_statistics = build_global_statistics(
		input_root=input_root,
		output_root=output_root,
		model_statistics=model_statistics,
		errors=errors,
		chunk_size=args.chunk_size,
	)

	write_json(
		global_statistics,
		output_root / "statistics.json",
	)

	write_statistics_csv(
		model_statistics,
		output_root / "statistics.csv",
	)

	print()
	print("=" * 70)
	print("Completed")
	print("=" * 70)
	print(
		f"Processed models: "
		f"{len(model_statistics)}"
	)
	print(
		f"Failed models: "
		f"{len(errors)}"
	)
	print(
		f"Total samples: "
		f"{global_statistics['totals']['total_samples']}"
	)
	print(
		f"Selected resolved != 1: "
		f"{global_statistics['totals']['selected_samples']}"
	)
	print(
		f"Excluded resolved == 1: "
		f"{global_statistics['totals']['excluded_resolved_1_samples']}"
	)
	print(
		f"JSONL chunks: "
		f"{global_statistics['totals']['chunks_written']}"
	)
	print(
		f"Resolved distribution: "
		f"{global_statistics['totals']['resolved_counts']}"
	)
	print(
		f"Output directory: "
		f"{output_root.resolve()}"
	)
	print(
		f"Global JSON statistics: "
		f"{(output_root / 'statistics.json').resolve()}"
	)
	print(
		f"Global CSV statistics: "
		f"{(output_root / 'statistics.csv').resolve()}"
	)


if __name__ == "__main__":
	main()