#!/usr/bin/env python3
"""
test_smoke.py — Book Downloader 冒烟测试
运行: python test_smoke.py
"""
import os
import sys
import importlib.util
import py_compile

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(PROJECT_DIR, "backend")
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")

# Add backend to path
sys.path.insert(0, BACKEND_DIR)

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  [PASS] {name}")
    except Exception as e:
        failed += 1
        print(f"  [FAIL] {name}: {e}")

def main():
    print("\n  Book Downloader - Smoke Test\n")

    # ==== Section 1: File Structure (10 tests) ====
    print("\n  [Section 1] File Structure")
    print("  " + "-" * 40)

    test("version.py exists", lambda: assert_file_exists(os.path.join(BACKEND_DIR, "version.py")))
    test("config.py exists", lambda: assert_file_exists(os.path.join(BACKEND_DIR, "config.py")))
    test("main.py exists", lambda: assert_file_exists(os.path.join(BACKEND_DIR, "main.py")))
    test("search.py exists", lambda: assert_file_exists(os.path.join(BACKEND_DIR, "api", "search.py")))
    test("flaresolverr.py exists", lambda: assert_file_exists(os.path.join(BACKEND_DIR, "engine", "flaresolverr.py")))
    test("requirements.txt exists", lambda: assert_file_exists(os.path.join(BACKEND_DIR, "requirements.txt")))
    test("frontend/package.json exists", lambda: assert_file_exists(os.path.join(FRONTEND_DIR, "package.json")))
    test("setup.iss exists", lambda: assert_file_exists(os.path.join(PROJECT_DIR, "setup.iss")))
    test("release.py exists", lambda: assert_file_exists(os.path.join(PROJECT_DIR, "release.py")))
    test("README.md exists", lambda: assert_file_exists(os.path.join(PROJECT_DIR, "README.md")))

    # ==== Section 2: Python Syntax (1 test) ====
    print("\n  [Section 2] Python Syntax Check")
    print("  " + "-" * 40)

    def check_all_python_syntax():
        """Walk backend/ dir, compile every .py file, report any SyntaxError"""
        errors = []
        for root, dirs, files in os.walk(BACKEND_DIR):
            # Skip venv and __pycache__ directories
            dirs[:] = [d for d in dirs if d not in ('venv', '__pycache__', '.git', 'node_modules')]
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    try:
                        py_compile.compile(filepath, doraise=True)
                    except py_compile.PyCompileError as e:
                        errors.append(f"{filepath}: {e}")
        if errors:
            raise AssertionError(f"Syntax errors found:\n" + "\n".join(errors))

    test("All .py files compile without syntax errors", check_all_python_syntax)

    # ==== Section 3: Version (2 tests) ====
    print("\n  [Section 3] Version Module")
    print("  " + "-" * 40)

    def test_version_module():
        spec = importlib.util.spec_from_file_location("version", os.path.join(BACKEND_DIR, "version.py"))
        version_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(version_module)
        return version_module

    version_module = None
    def load_and_check_version():
        nonlocal version_module
        version_module = test_version_module()
        assert hasattr(version_module, 'VERSION'), "VERSION not found in version module"
        assert isinstance(version_module.VERSION, str), "VERSION should be a string"
        assert len(version_module.VERSION) > 0, "VERSION should not be empty"

    def check_github_repo():
        nonlocal version_module
        if version_module is None:
            version_module = test_version_module()
        assert hasattr(version_module, 'GITHUB_REPO'), "GITHUB_REPO not found in version module"
        assert isinstance(version_module.GITHUB_REPO, str), "GITHUB_REPO should be a string"
        assert len(version_module.GITHUB_REPO) > 0, "GITHUB_REPO should not be empty"

    test("VERSION is a non-empty string", load_and_check_version)
    test("GITHUB_REPO is a non-empty string", check_github_repo)

    # ==== Section 4: Config (3 tests) ====
    print("\n  [Section 4] Config Module")
    print("  " + "-" * 40)

    def test_config_module():
        spec = importlib.util.spec_from_file_location("config", os.path.join(BACKEND_DIR, "config.py"))
        config_module = importlib.util.module_from_spec(spec)
        # Mock sys.frozen to avoid app data path issues during testing
        original_frozen = getattr(sys, 'frozen', False)
        sys.frozen = False
        try:
            spec.loader.exec_module(config_module)
        finally:
            sys.frozen = original_frozen
        return config_module

    config_module = None
    def check_default_config():
        nonlocal config_module
        config_module = test_config_module()
        assert hasattr(config_module, 'DEFAULT_CONFIG'), "DEFAULT_CONFIG not found in config module"
        assert isinstance(config_module.DEFAULT_CONFIG, dict), "DEFAULT_CONFIG should be a dict"
        assert len(config_module.DEFAULT_CONFIG) > 0, "DEFAULT_CONFIG should not be empty"

    def check_config_keys():
        nonlocal config_module
        if config_module is None:
            config_module = test_config_module()
        required_keys = ['host', 'port', 'download_dir']
        for key in required_keys:
            assert key in config_module.DEFAULT_CONFIG, f"Config missing required key: {key}"

    def test_load_config():
        nonlocal config_module
        if config_module is None:
            config_module = test_config_module()
        config = config_module.load_config()
        assert isinstance(config, dict), "load_config should return a dict"
        assert 'host' in config, "loaded config should have 'host' key"
        assert 'port' in config, "loaded config should have 'port' key"

    test("DEFAULT_CONFIG is a dict with expected keys", check_default_config)
    test("Config has 'host', 'port', 'download_dir' keys", check_config_keys)
    test("load_config returns a dict", test_load_config)

    # ==== Section 5: Search Engine (2 tests) ====
    print("\n  [Section 5] Search Engine")
    print("  " + "-" * 40)

    def test_search_engine_module():
        spec = importlib.util.spec_from_file_location("search_engine", os.path.join(BACKEND_DIR, "search_engine.py"))
        search_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(search_module)
        return search_module

    search_module = None
    def check_search_engine_class():
        nonlocal search_module
        search_module = test_search_engine_module()
        assert hasattr(search_module, 'SearchEngine'), "SearchEngine class not found"
        assert callable(search_module.SearchEngine), "SearchEngine should be callable (a class)"

    def check_search_engine_methods():
        nonlocal search_module
        if search_module is None:
            search_module = test_search_engine_module()
        SearchEngine = search_module.SearchEngine
        engine = SearchEngine()
        assert hasattr(engine, 'set_db_dir'), "SearchEngine should have set_db_dir method"
        assert callable(engine.set_db_dir), "set_db_dir should be callable"
        assert hasattr(engine, 'search'), "SearchEngine should have search method"
        assert callable(engine.search), "search should be callable"

    test("SearchEngine class exists and is importable", check_search_engine_class)
    test("SearchEngine has set_db_dir and search methods", check_search_engine_methods)

    # ==== Section 6: Task Store (1 test) ====
    print("\n  [Section 6] Task Store")
    print("  " + "-" * 40)

    def test_task_store_module():
        # Need to mock config module first since task_store imports from it
        spec = importlib.util.spec_from_file_location("config", os.path.join(BACKEND_DIR, "config.py"))
        config_module = importlib.util.module_from_spec(spec)
        original_frozen = getattr(sys, 'frozen', False)
        sys.frozen = False
        try:
            spec.loader.exec_module(config_module)
        finally:
            sys.frozen = original_frozen
        sys.modules['config'] = config_module

        spec = importlib.util.spec_from_file_location("task_store", os.path.join(BACKEND_DIR, "task_store.py"))
        task_store_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(task_store_module)
        return task_store_module

    task_store_module = None
    def check_task_store():
        nonlocal task_store_module
        task_store_module = test_task_store_module()
        assert hasattr(task_store_module, 'task_store'), "task_store not found in module"
        # TaskStore has _tasks as a private dict attribute (not a property)
        assert hasattr(task_store_module.task_store, '_tasks'), "task_store should have _tasks attribute"
        assert isinstance(task_store_module.task_store._tasks, dict), "_tasks should be a dict"

    test("task_store has _tasks attribute", check_task_store)

    # ==== Section 7: Frontend (1 test) ====
    print("\n  [Section 7] Frontend Build")
    print("  " + "-" * 40)

    test("frontend/dist/index.html exists", lambda: assert_file_exists(os.path.join(FRONTEND_DIR, "dist", "index.html")))

    # ==== Section 8: PDF Parallel (1 test) ====
    print("\n  [Section 8] PDF Parallel")
    print("  " + "-" * 40)

    test("pdf split/merge round-trip", test_pdf_split_merge)

    # ==== Section 9: API Route Registration (3 tests) ====
    print("\n  [Section 9] API Route Registration")
    print("  " + "-" * 40)

    def test_api_search_importable():
        spec = importlib.util.spec_from_file_location("search_api", os.path.join(BACKEND_DIR, "api", "search.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, 'router'), "search.py should export 'router'"
        routes = [r.path for r in mod.router.routes]
        assert '/api/v1/search' in routes, "search route missing"
        assert '/api/v1/config' in routes, "config route missing"

    def test_api_tasks_importable():
        spec = importlib.util.spec_from_file_location("tasks_api", os.path.join(BACKEND_DIR, "api", "tasks.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, 'router'), "tasks.py should export 'router'"
        routes = [r.path for r in mod.router.routes]
        assert any('/api/v1/tasks' in p for p in routes), "tasks list route missing"

    def test_pipeline_steps_consistency():
        task_store_module = sys.modules.get('task_store')
        if task_store_module is None:
            spec = importlib.util.spec_from_file_location("task_store", os.path.join(BACKEND_DIR, "task_store.py"))
            task_store_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(task_store_module)
        steps = task_store_module.PIPELINE_STEPS
        assert len(steps) == 7, f"Expected 7 pipeline steps, got {len(steps)}"
        for step in ['fetch_metadata', 'fetch_isbn', 'download_pages', 'convert_pdf', 'ocr', 'bookmark', 'finalize']:
            assert step in steps, f"Missing step: {step}"

    test("search API router has expected routes", test_api_search_importable)
    test("tasks API router has expected routes", test_api_tasks_importable)
    test("pipeline has all 7 expected steps", test_pipeline_steps_consistency)

    # ==== Summary ====
    total = passed + failed
    print(f"\n  {'='*40}")
    print(f"  Result: {passed}/{total} passed")
    if failed > 0:
        print(f"  {failed} test(s) FAILED")
        sys.exit(1)
        print("  All smoke tests passed!")
    print()

def assert_file_exists(filepath):
    """Assert that a file exists"""
    assert os.path.exists(filepath), f"File not found: {filepath}"
    assert os.path.isfile(filepath), f"Path exists but is not a file: {filepath}"

def test_pdf_split_merge():
    """Test that split_pdf and merge_pdfs round-trip correctly."""
    import fitz, os, tempfile
    from engine.pdf_parallel import split_pdf, merge_pdfs

    # Create a 5-page test PDF
    doc = fitz.open()
    for i in range(5):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50 + i * 20), f"Page {i+1}", fontname="helv", fontsize=12)

    fd, pdf_path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    doc.save(pdf_path)
    doc.close()

    try:
        chunks = split_pdf(pdf_path, 3)
        assert len(chunks) == 3, f"Expected 3 chunks, got {len(chunks)}"

        # Verify total pages match
        total = 0
        for c in chunks:
            d = fitz.open(c)
            total += len(d)
            d.close()
        assert total == 5, f"Expected 5 pages total, got {total}"

        # Merge back
        merged_path = pdf_path.replace('.pdf', '_merged.pdf')
        ok = merge_pdfs(chunks, merged_path)
        assert ok, "merge_pdfs failed"
        assert os.path.exists(merged_path)

        d = fitz.open(merged_path)
        assert len(d) == 5, f"Merged PDF has {len(d)} pages, expected 5"
        for i in range(5):
            text = d[i].get_text().strip()
            assert f"Page {i+1}" in text, f"Page {i+1} text mismatch: {text}"
        d.close()

        # Cleanup
        for c in chunks:
            os.remove(c)
        os.remove(merged_path)
    finally:
        os.remove(pdf_path)


if __name__ == "__main__":
    main()
