import uvicorn

import webpage
from runtime_fixes import apply_patches


def main():
    apply_patches(webpage)
    uvicorn.run(webpage.app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
