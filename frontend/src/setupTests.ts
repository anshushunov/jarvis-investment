import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// В проекте не включён test.globals, поэтому автоматическая очистка DOM между
// тестами из @testing-library/react (которая полагается на глобальный
// afterEach) сама не регистрируется — без этого расхождения из одного теста
// накапливались бы в document.body следующего.
afterEach(cleanup);
