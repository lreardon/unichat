# Frontend MVP (Flutter)

This is a minimal Flutter client for the backend API.

## Initialize project files (once)

From repository root:

```bash
cd frontend
flutter create .
```

Then restore this file if overwritten and keep `lib/main.dart` from this repository.

## Run

```bash
cd frontend
flutter pub get
flutter run -d chrome --dart-define=API_BASE=http://127.0.0.1:8000
```

The app calls:
- `POST /query`
