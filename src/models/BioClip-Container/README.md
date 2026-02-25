# BioClip Container

This directory holds a small Flask service that wraps the `BioClipModel`.
It exposes a single endpoint:

* `POST /analyze_images` – payload `{ "images": [base64, ...] }`, returns
  `{ "results": [ [speciesList, confidenceList], ... ] }`.

To build and run:

```sh
cd src/models/BioClip-Container
docker build -t bioclip-service .
docker run -p 5000:5000 bioclip-service
```

Environment variables allow configuration of model paths and options.
