# ReSTIR Atlas validation

Run the data and scaffold checks from the repository root. Run the frontend checks from `web/restir-map/`.

~~~text
python -B scripts/check_scaffold.py
python -B scripts/check_literature.py
python -B -m unittest tests.workflows.test_literature_data -v
npm test
npm run build
~~~

The Python checks cover IDs, relationship direction, evidence fields, figure hashes and matrix consistency. Review the quoted source location when changing a relationship. Manuscripts and the limits of the available evidence are recorded in the [audit](audit.json). The [frontend guide](../../../web/restir-map/README.md) documents the build and deployment.
