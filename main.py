import uvicorn
import webpage


def main():
    uvicorn.run(webpage.app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
