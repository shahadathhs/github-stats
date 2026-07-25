.PHONY: generate commit clean

# Generate the statistics SVG images into generated/
generate:
	uv run python -m github_stats

# Commit generated images back to the repository (used by CI)
commit:
	git config --global user.name "github-actions[bot]"
	git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"
	git add .
	git commit -m 'Update generated files' || true
	git push

# Remove generated images
clean:
	rm -rf generated
