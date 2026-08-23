import re
import sqlite3
import tempfile
from pathlib import Path


# ============================================================
# Configuration
# ============================================================

INPUT_FILE = Path(
	"Nebius-SWE-agent.jsonl"
)

OUTPUT_FILE = Path(
	"Nebius-SWE-agent-sorted.jsonl"
)

BATCH_SIZE = 1_000


# Match:
# "trajectory_id": "Melevir__cognitive_complexity-15_41"
#
# The rest of the line does not need to be valid JSON.
TRAJECTORY_ID_PATTERN = re.compile(
	r'"trajectory_id"\s*:\s*"([^"\r\n]+)"'
)


# Match the final integer after the last underscore.
#
# Example:
# Melevir__cognitive_complexity-15_41 -> 41
TRAILING_INDEX_PATTERN = re.compile(
	r"_(\d+)$"
)


# ============================================================
# Extract trajectory ID
# ============================================================

def extract_trajectory_id(
	raw_line: str,
	line_number: int,
) -> str:

	match = TRAJECTORY_ID_PATTERN.search(
		raw_line
	)

	if match is None:

		preview = raw_line[:300]

		raise ValueError(
			f"Line {line_number}: cannot find a valid "
			f'"trajectory_id": "..." field.\n'
			f"Line preview:\n"
			f"{preview}"
		)

	trajectory_id = match.group(1)

	return trajectory_id


# ============================================================
# Extract numeric sort index
# ============================================================

def extract_trajectory_index(
	raw_line: str,
	line_number: int,
) -> int:

	trajectory_id = extract_trajectory_id(
		raw_line=raw_line,
		line_number=line_number,
	)

	match = TRAILING_INDEX_PATTERN.search(
		trajectory_id
	)

	if match is None:

		raise ValueError(
			f"Line {line_number}: trajectory_id does not end "
			f"with _<number>: {trajectory_id!r}"
		)

	return int(
		match.group(1)
	)


# ============================================================
# Insert buffered records
# ============================================================

def insert_records(
	connection: sqlite3.Connection,
	insert_buffer: list[tuple[int, int, str]],
) -> None:

	if not insert_buffer:
		return

	connection.executemany(
		"""
		INSERT INTO records (
			trajectory_index,
			line_number,
			raw_line
		)
		VALUES (?, ?, ?)
		""",
		insert_buffer,
	)

	connection.commit()

	insert_buffer.clear()


# ============================================================
# Sort JSONL-like file
# ============================================================

def sort_jsonl(
	input_file: Path,
	output_file: Path,
) -> None:

	if not input_file.exists():

		raise FileNotFoundError(
			f"Input file does not exist: "
			f"{input_file.resolve()}"
		)

	if not input_file.is_file():

		raise ValueError(
			f"Input path is not a file: "
			f"{input_file.resolve()}"
		)

	if input_file.resolve() == output_file.resolve():

		raise ValueError(
			"Input and output files must be different."
		)

	if output_file.exists():

		raise FileExistsError(
			f"Output file already exists: "
			f"{output_file.resolve()}\n"
			"Delete it before running the script again."
		)

	output_file.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	total_records = 0
	blank_lines = 0

	min_index: int | None = None
	max_index: int | None = None

	temporary_output = output_file.with_name(
		output_file.name + ".tmp"
	)

	if temporary_output.exists():

		raise FileExistsError(
			f"Temporary output file already exists: "
			f"{temporary_output.resolve()}\n"
			"Delete it before running the script again."
		)

	try:

		with tempfile.TemporaryDirectory(
			prefix="nebius_trajectory_sort_"
		) as temporary_directory:

			database_path = (
				Path(temporary_directory)
				/
				"sort.db"
			)

			connection = sqlite3.connect(
				database_path
			)

			try:

				# Improve temporary bulk-insert speed.
				connection.execute(
					"PRAGMA journal_mode = OFF"
				)

				connection.execute(
					"PRAGMA synchronous = OFF"
				)

				connection.execute(
					"PRAGMA temp_store = FILE"
				)

				connection.execute(
					"""
					CREATE TABLE records (
						trajectory_index INTEGER NOT NULL,
						line_number INTEGER NOT NULL,
						raw_line TEXT NOT NULL,
						PRIMARY KEY (line_number)
					)
					"""
				)

				# Explicit index for ORDER BY efficiency.
				connection.execute(
					"""
					CREATE INDEX idx_records_sort
					ON records (
						trajectory_index,
						line_number
					)
					"""
				)

				insert_buffer: list[
					tuple[int, int, str]
				] = []

				with input_file.open(
					"r",
					encoding="utf-8",
				) as input_stream:

					for line_number, raw_line in enumerate(
						input_stream,
						start=1,
					):

						# Remove only the physical newline.
						# Do not modify spaces or other content.
						raw_line = raw_line.rstrip(
							"\r\n"
						)

						if not raw_line.strip():

							blank_lines += 1
							continue

						trajectory_index = (
							extract_trajectory_index(
								raw_line=raw_line,
								line_number=line_number,
							)
						)

						insert_buffer.append((
							trajectory_index,
							line_number,
							raw_line,
						))

						total_records += 1

						if min_index is None:

							min_index = trajectory_index
							max_index = trajectory_index

						else:

							min_index = min(
								min_index,
								trajectory_index,
							)

							max_index = max(
								max_index,
								trajectory_index,
							)

						if len(insert_buffer) >= BATCH_SIZE:

							insert_records(
								connection=connection,
								insert_buffer=insert_buffer,
							)

							print(
								f"\rLoaded "
								f"{total_records:,} records",
								end="",
								flush=True,
							)

				insert_records(
					connection=connection,
					insert_buffer=insert_buffer,
				)

				print(
					f"\rLoaded {total_records:,} records"
				)

				written_records = 0

				with temporary_output.open(
					"w",
					encoding="utf-8",
					newline="\n",
				) as output_stream:

					cursor = connection.execute(
						"""
						SELECT raw_line
						FROM records
						ORDER BY
							trajectory_index ASC,
							line_number ASC
						"""
					)

					for row in cursor:

						output_stream.write(
							row[0]
						)

						output_stream.write(
							"\n"
						)

						written_records += 1

						if (
							written_records % BATCH_SIZE
							==
							0
						):

							print(
								f"\rWritten "
								f"{written_records:,}/"
								f"{total_records:,} records",
								end="",
								flush=True,
							)

				if written_records != total_records:

					raise RuntimeError(
						f"Record count mismatch: loaded "
						f"{total_records:,}, but wrote "
						f"{written_records:,}."
					)

				temporary_output.replace(
					output_file
				)

			finally:

				connection.close()

	except Exception:

		if temporary_output.exists():

			temporary_output.unlink()

		raise

	print()
	print("=" * 60)
	print("Sorting completed")
	print("=" * 60)
	print(
		f"Input records:  {total_records:,}"
	)
	print(
		f"Blank lines:    {blank_lines:,}"
	)
	print(
		f"Minimum index:  {min_index}"
	)
	print(
		f"Maximum index:  {max_index}"
	)
	print(
		f"Output file:    {output_file.resolve()}"
	)


# ============================================================
# Main
# ============================================================

def main() -> None:

	sort_jsonl(
		input_file=INPUT_FILE,
		output_file=OUTPUT_FILE,
	)


if __name__ == "__main__":
	main()